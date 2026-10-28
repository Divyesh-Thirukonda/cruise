# Cruise

**One device. Tell it what you need it to become.**

Cruise is a proposed programmable physical controller: ask the same buttons and knobs to become a music controller, then a video-editing controller. Meta AI interprets the request against the hardware actually connected and produces a configuration the device can validate and run.

The hardware stays the same; its controls, labels, and behavior change. The proposed differentiator is adapting to a new request live, including follow-up edits, instead of selecting only from fixed presets.

## Status

Repository and project planning established on October 27, 2026 for the Meta Global AI Developer Hackathon. **No working device, model integration, or application is implemented yet.** Hardware inventory, competition track, and API access are still to be confirmed.

## First demo to build

1. Ask for a music controller; turn a physical knob and hear the connected host application respond.
2. Ask the same device to become a video-editing controller; show controls and labels changing together.
3. Give it a fresh request, such as swapping two controls or changing a knob's range. Show the validated change and its physical effect.
4. Request something the attached hardware cannot do. Show a useful limitation and preserve the working configuration.

This is a build target, not a claim about current capabilities. The exact controls and host actions will follow the team's hardware inventory.

## Project context

| Document | Purpose |
| --- | --- |
| [Agent instructions](AGENTS.md) | How coding agents should work in this repository |
| [Product brief](context/product-brief.md) | Audience, differentiation, scope, and demo story |
| [Hackathon facts](context/hackathon.md) | Source-backed rules, rubric, dates, and unresolved discrepancies |
| [Architecture](context/architecture.md) | Proposed capability-aware configuration and device execution |
| [Build plan](context/plan.md) | Priorities, milestones, and evidence to collect |
| [Decisions](context/decisions.md) | Assumptions and choices that need team input |
| [Build log](context/build-log.md) | What was actually created during the event |
| [Submission checklist](context/submission-checklist.md) | Public repo, three-minute video, and submission readiness |

The supplied participant guide weights **Impact 30%, Meta AI tooling 25%, Technical Depth & Execution 20%, Demo 25%**. These guide our priorities; they do not guarantee a placing.

## Collaborate

```sh
git clone https://github.com/Divyesh-Thirukonda/cruise.git
cd cruise
git switch -c your-name/short-description
```

Read the product brief and build plan, then follow [CONTRIBUTING.md](CONTRIBUTING.md). There is no install, run, or test command yet; add verified commands with the first implementation.

The repository is public for judging. Keep API keys, private conversations, account details, and raw participant materials out of commits. A project license has not yet been selected by the team.
