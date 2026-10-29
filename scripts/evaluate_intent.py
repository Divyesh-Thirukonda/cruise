#!/usr/bin/env python3
"""Typed live Studio intent evaluations; dry plan unless --run is explicit.

Uses only the local Studio API. It never contacts a model or operates a browser
directly. Evidence omits prompts, replies, screenshots, source and private text.
No automatic restoration, context clearing, approval or cancellation occurs.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import http.cookiejar
import json
import math
from pathlib import Path
import re
import time
import urllib.error
import urllib.parse
import urllib.request


SKILLS = {"computer-use", "device-apps", "games", "hardware-controls", "hardware-debugger"}
CONTROLS = {"joystick", "encoder", "button_a", "button_b", "encoder_pressed"}
TOOLS = {"load_skill", "read_recent_context", "inspect_capabilities", "read_runtime_api",
         "read_current_package", "write_package", "test_package", "preview_package",
         "activate_package", "delegate_task", "ask_user", "computer_observe", "computer_act",
         "computer_audio", "camera_control", "system_control", "speaker_control", "hardware_debug"}
OPERATIONS = {"get", "set", "delta", "mute", "start", "stop", "status",
              "volume.get", "volume.set", "volume.delta", "volume.mute",
              "brightness.get", "brightness.set", "brightness.delta"}


class EvaluationError(Exception):
    """Only fixed, content-free error categories belong in evidence."""


def step(name, request, **expect):
    return {"name": name, "request": request, "expect": expect}


SCENARIOS = {
    "speaker": [
        step("seed_speaker_40", "Set the Modulate Pi speaker volume to 40 percent.", speaker=40, preserve_mac=True),
        step("speaker_explicit_step", "Make it ten louder.", speaker=50, preserve_mac=True),
        step("speaker_reuse_step", "Make it louder.", speaker=60, preserve_mac=True),
        step("speaker_undo_last", "Undo that.", speaker=50, preserve_mac=True),
        step("speaker_original_level", "Back to the level before those two increases.", speaker=40, preserve_mac=True),
    ],
    "mac": [
        step("seed_mac_30", "Set my Mac's system volume to 30 percent.", mac=30, preserve_speaker=True),
        step("mac_vague_increase", "Make it ten higher.", mac=40, preserve_speaker=True),
        step("mac_undo", "Undo that.", mac=30, preserve_speaker=True),
    ],
    "remap": [
        step("brightness_plus_two", "Use the knob to control my Mac's screen brightness, two percentage points per clockwise step.", binding=["brightness.delta", 2]),
        step("reverse_mapping", "Reverse it.", binding=["brightness.delta", -2]),
        step("halve_mapping", "Half as sensitive.", binding=["brightness.delta", -1]),
        step("shift_mapping_target", "Now use it for volume instead, same direction and sensitivity.", binding=["volume.delta", -1]),
    ],
    "game": [
        step("create_dodger", "Create a simple joystick dodging game with original artwork. Use the joystick for movement.", new_game=True),
        step("slower_same_controls", "Make it slower, keeping the same controls.", new_game=True, same_controls=True,
             manual="Compare gameplay speed and confirm it is slower; software activation alone cannot establish this."),
    ],
    "app": [
        step("create_counter", "Create a simple on-device counter with original artwork. The green button adds one and the red button subtracts one.", new_game=True),
        step("counter_green_subtracts", "Make the green button subtract instead.", new_game=True, same_controls=True,
             manual="Press the physical green button and verify the counter decreases; source/activation alone is insufficient."),
    ],
    "missing-context": [step("missing_referent", "Do that again.", clarification=True, no_mutations=True)],
}
for _scenario, _skill in {"speaker": "hardware-controls", "mac": "hardware-controls",
                         "remap": "hardware-controls", "game": "games", "app": "device-apps"}.items():
    for _step in SCENARIOS[_scenario]:
        _step["expect"]["expected_skill"] = _skill


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise EvaluationError("studio_redirect_refused")


class Studio:
    def __init__(self, url):
        parsed = urllib.parse.urlsplit(url)
        if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}
                or parsed.username or parsed.password or parsed.query or parsed.fragment
                or parsed.path not in {"", "/"}):
            raise EvaluationError("studio_must_be_local_http_origin")
        self.origin = url.rstrip("/")
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect(),
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.token = None

    def call(self, path, body=None, timeout=5):
        headers = {"Accept": "application/json", "Origin": self.origin}
        data = None
        if body is not None:
            if self.token is None:
                token = self.call("/api/csrf").get("token")
                if type(token) is not str or not token:
                    raise EvaluationError("csrf_token_unavailable")
                self.token = token
            headers.update({"Content-Type": "application/json", "X-CSRF-Token": self.token})
            data = json.dumps(body, allow_nan=False).encode()
        request = urllib.request.Request(self.origin + path, data=data, headers=headers)
        try:
            with self.opener.open(request, timeout=max(.05, timeout)) as response:
                raw = response.read(2_000_001)
            if len(raw) > 2_000_000:
                raise EvaluationError("studio_response_too_large")
            result = json.loads(raw)
            if type(result) is not dict:
                raise EvaluationError("invalid_studio_response")
            return result
        except urllib.error.HTTPError as error:
            raise EvaluationError(f"studio_http_{error.code}") from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise EvaluationError("studio_unavailable") from None
        except (ValueError, TypeError):
            raise EvaluationError("invalid_studio_response") from None


def numeric(value):
    return type(value) in (int, float) and math.isfinite(value)


def setting(value):
    if type(value) is not dict:
        return {}
    result = {key: value[key] for key in ("volume", "brightness")
              if type(value.get(key)) is int and 0 <= value[key] <= 100}
    result.update({key: value[key] for key in ("muted", "available") if type(value.get(key)) is bool})
    return result


def revision(value):
    return value if type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) else None


def snapshot(state):
    active = state.get("active") or {}
    package = active.get("package") or {}
    bindings = []
    for binding in package.get("bindings", []):
        if (type(binding) is dict and binding.get("control") == "encoder"
                and binding.get("action") in {"volume.delta", "brightness.delta"}
                and numeric(binding.get("scale")) and -10 <= binding["scale"] <= 10):
            bindings.append({key: binding[key] for key in ("control", "action", "scale")})
    return {"device_connected": state.get("device", {}).get("connected") is True,
            "paired": state.get("paired") is True,
            "speaker": setting(state.get("speaker_volume")), "mac_cached": setting(state.get("volume")),
            "revision": revision(active.get("revision")),
            "kind": package.get("kind") if package.get("kind") in {"game", "control"} else None,
            "controls": sorted(c for c in package.get("controls", []) if c in CONTROLS),
            "bindings": bindings, "stream_running": (state.get("computer_audio") or {}).get("running") is True}


def budget_delta(before, after):
    result = {}
    for key in ("calls", "charged_or_reserved_dollars"):
        left, right = before.get("budget", {}).get(key), after.get("budget", {}).get(key)
        if numeric(left) and numeric(right):
            result[key] = round(right - left, 6)
    return result


def event_summary(events):
    calls, failures, operations = Counter(), Counter(), Counter()
    skills, mac, ack_revisions = set(), None, set()
    mutations = 0
    for event in sorted(events.values(), key=lambda value: value["id"]):
        if event.get("type") != "tool_finished" or event.get("tool") not in TOOLS:
            continue
        tool = event["tool"]
        calls[tool] += 1
        operation = event.get("operation")
        if operation in OPERATIONS:
            operations[f"{tool}:{operation}"] += 1
        if tool in {"write_package", "activate_package", "computer_act"}:
            mutations += 1
        elif tool in {"system_control", "speaker_control", "camera_control", "computer_audio"}:
            if operation not in {"get", "status", "volume.get", "brightness.get"}:
                mutations += 1  # A failed write may still have had a side effect.
        if event.get("status") == "failed":
            failures[tool] += 1
            continue
        detail = event.get("detail") if type(event.get("detail")) is dict else {}
        if tool == "load_skill":
            name = event.get("skill", detail.get("id"))
            if name in SKILLS:
                skills.add(name)
        if tool == "system_control":
            observed = setting(detail.get("after", detail))
            if "volume" in observed:
                mac = observed
        if tool == "activate_package" and detail.get("device_acknowledged") is True:
            value = revision(detail.get("revision"))
            if value:
                ack_revisions.add(value)
    return {"tools": dict(calls), "tool_failures": dict(failures), "tool_failure_count": sum(failures.values()),
            "operations": dict(operations), "skills": sorted(skills), "ask_user_count": calls["ask_user"],
            "mutating_tool_count": mutations, "mac_observed": mac,
            "acknowledged_revisions": sorted(ack_revisions)}


def verify(expect, before, after, activity):
    left, right = snapshot(before), snapshot(after)
    checks = []
    def check(name, passed):
        checks.append({"name": name, "passed": bool(passed)})
    check("job_completed", after.get("agent", {}).get("status") == "completed")
    check("device_connected", right["device_connected"])
    if "expected_skill" in expect:
        check("appropriate_skill_loaded", expect["expected_skill"] in activity["skills"])
    question = bool(after.get("clarification"))
    check("expected_clarification_state", question == bool(expect.get("clarification")))
    if "speaker" in expect:
        check("exact_pi_speaker_level", right["speaker"].get("available") is True
              and right["speaker"].get("volume") == expect["speaker"])
    if "mac" in expect:
        check("exact_native_mac_readback", (activity["mac_observed"] or {}).get("volume") == expect["mac"])
    if expect.get("preserve_speaker"):
        check("pi_speaker_unchanged", left["speaker"].get("available") is True
              and right["speaker"] == left["speaker"])
    if expect.get("preserve_mac"):
        mac_writes = sum(count for operation, count in activity["operations"].items()
                         if operation.startswith("system_control:volume.") and not operation.endswith(".get"))
        unknown = activity["tools"].get("system_control", 0) > sum(
            count for operation, count in activity["operations"].items() if operation.startswith("system_control:"))
        check("no_mac_volume_mutation", mac_writes == 0 and not unknown)
        check("cached_mac_state_unchanged", left["mac_cached"] == right["mac_cached"])
    if "speaker" in expect or "mac" in expect:
        check("app_revision_unchanged", left["revision"] == right["revision"])
        old_stream, new_stream = before.get("computer_audio") or {}, after.get("computer_audio") or {}
        check("stream_preserved", old_stream.get("running") == new_stream.get("running")
              and old_stream.get("session") == new_stream.get("session"))
    if "binding" in expect:
        action, scale = expect["binding"]
        check("exact_encoder_binding", right["kind"] == "control" and right["bindings"] ==
              [{"control": "encoder", "action": action, "scale": scale}])
        paired = after.get("device", {}).get("capabilities", {}).get("paired_host") or {}
        target = ((after.get("active") or {}).get("package") or {}).get("target")
        check("binding_targets_paired_mac", target is not None and target == paired.get("session_id"))
    if expect.get("new_game") or "binding" in expect:
        check("new_acknowledged_revision", right["revision"] is not None and right["revision"] != left["revision"]
              and right["revision"] in activity["acknowledged_revisions"])
    if expect.get("new_game"):
        check("application_runtime", right["kind"] == "game")
    if expect.get("same_controls"):
        check("same_controls", bool(left["controls"]) and right["controls"] == left["controls"])
    if expect.get("no_mutations"):
        check("no_mutating_tools", activity["mutating_tool_count"] == 0)
        check("asked_for_missing_referent", activity["ask_user_count"] >= 1)
        check("app_unchanged", left["revision"] == right["revision"])
        check("settings_unchanged", left["speaker"] == right["speaker"] and left["mac_cached"] == right["mac_cached"])
    return checks


def run_step(studio, item, timeout, interval):
    before = studio.call("/api/state")
    if before.get("agent", {}).get("running"):
        raise EvaluationError("another_request_is_running")
    if before.get("clarification"):
        raise EvaluationError("existing_clarification_requires_operator")
    if before.get("device", {}).get("connected") is not True:
        raise EvaluationError("device_disconnected")
    accepted = studio.call("/api/request", {"text": item["request"]})
    job = accepted.get("job_id")
    if type(job) is not str or not re.fullmatch(r"[0-9a-f]{32}", job):
        raise EvaluationError("accepted_job_identity_missing")
    started, events = time.monotonic(), {}
    deadline = started + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise EvaluationError("job_timeout_may_still_be_running")
        after = studio.call("/api/state", timeout=min(5, remaining))
        for event in after.get("events", []):
            if type(event) is dict and type(event.get("id")) is int and event.get("job_id") == job:
                events[event["id"]] = event
        agent = after.get("agent") or {}
        if agent.get("job_id") != job:
            raise EvaluationError("job_superseded_stop_evaluation")
        if not agent.get("running"):
            break
        time.sleep(min(interval, max(0, deadline - time.monotonic())))
    activity = event_summary(events)
    checks = verify(item["expect"], before, after, activity)
    passed = all(check["passed"] for check in checks)
    return {"case": item["name"], "job_id": job, "input_mode": "typed_studio_live",
            "status": "passed_automated_checks" if passed else "failed",
            "seconds": round(time.monotonic() - started, 3), "checks": checks,
            "before": snapshot(before), "after": snapshot(after), "activity": activity,
            "budget_delta": budget_delta(before, after),
            "manual_inspection_required": item["expect"].get("manual"),
            "provider": after.get("provider") if after.get("provider") in {"meta", "ollama", "fireworks"} else "other"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--scenario", choices=SCENARIOS, help="Default: speaker")
    group.add_argument("--request", help="One typed request; never copied into evidence")
    parser.add_argument("--expect-speaker", type=int, choices=range(101), metavar="0..100")
    parser.add_argument("--expect-mac", type=int, choices=range(101), metavar="0..100")
    parser.add_argument("--run", action="store_true", help="Actually send requests to Studio")
    parser.add_argument("--clear-context", action="store_true", help="Explicitly clear remembered requests before running")
    parser.add_argument("--url", default="http://127.0.0.1:8787")
    parser.add_argument("--timeout", type=float, default=150, help="Per-job wait, at most 150 seconds")
    parser.add_argument("--poll-interval", type=float, default=.5)
    parser.add_argument("--output", type=Path, help="Optional sanitized JSON evidence file")
    args = parser.parse_args(argv)
    if not 0 < args.timeout <= 150 or not .2 <= args.poll_interval <= 2:
        parser.error("timeout must be 0..150 seconds; poll interval must be 0.2..2 seconds")
    if args.request is None and (args.expect_speaker is not None or args.expect_mac is not None):
        parser.error("explicit expectations apply only to --request")
    scenario = args.scenario or ("custom" if args.request is not None else "speaker")
    if args.request is not None:
        if not 1 <= len(args.request.strip()) <= 4000:
            parser.error("request must contain 1..4000 characters")
        expect = {}
        if args.expect_speaker is not None: expect["speaker"] = args.expect_speaker
        if args.expect_mac is not None: expect["mac"] = args.expect_mac
        if not expect:
            expect["manual"] = "Verify the requested outcome independently; no task-specific semantic oracle was configured."
        steps = [step("custom_request", args.request, **expect)]
    else:
        steps = SCENARIOS[scenario]
    evidence = {"schema": "modulate-intent-eval-v1", "scenario": scenario,
                "at": datetime.now(timezone.utc).isoformat(), "mode": "typed_studio_live" if args.run else "dry_plan",
                "context_clear_requested": args.clear_context, "results": [],
                "limits": ["Software readbacks and acknowledgements are not optical/audibility evidence.",
                           "Game speed and button meaning require the listed manual checks.",
                           "Ledger deltas include any concurrent account activity; unknown-cost holds remain.",
                           "No automatic restoration or cancellation; a timeout may leave the request running."]}
    if not args.run:
        evidence["plan"] = [{"case": item["name"], "request": item["request"] if scenario != "custom" else "[user-provided text omitted]",
                             "expect": item["expect"]} for item in steps]
        evidence["status"] = "not_run"
        if scenario == "missing-context":
            evidence["requires"] = "Use --clear-context with --run to establish missing context explicitly."
    else:
        try:
            studio = Studio(args.url)
            if scenario == "missing-context" and not args.clear_context:
                raise EvaluationError("missing_context_scenario_requires_explicit_clear_context")
            if args.clear_context:
                studio.call("/api/context/clear", {})
            for item in steps:
                result = run_step(studio, item, args.timeout, args.poll_interval)
                evidence["results"].append(result)
                if result["status"] == "failed":
                    break
            failed = any(result["status"] == "failed" for result in evidence["results"])
            manual = any(result["manual_inspection_required"] for result in evidence["results"])
            evidence["status"] = "failed" if failed else "manual_review_required" if manual else "passed_automated_checks"
        except EvaluationError as error:
            evidence.update(status="stopped", error=str(error))
        except KeyboardInterrupt:
            evidence.update(status="stopped", error="operator_interrupted_request_may_still_be_running")
    rendered = json.dumps(evidence, indent=2, allow_nan=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered)
    print(rendered, end="")
    return 1 if evidence["status"] in {"failed", "stopped"} else 0


if __name__ == "__main__":
    raise SystemExit(main())
