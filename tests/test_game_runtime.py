"""These small games are test fixtures, never production fallback content."""
import copy
import os
import time
import unittest

from modulate.game_runtime import (Game, GameError, validate_package, validate_input,
    validate_state, validate_commands, verify, MAX_CODE_BYTES)


GAME_CODE = """
function init(){return {x:120,y:60,score:0};}
function update(s,input,dt){
  s.x += input.joystick_x*60*dt + input.encoder_delta;
  s.y += input.joystick_y*60*dt;
  if(input.button_a) s.score += 1;
  if(input.button_b) s.score -= 1;
  if(input.encoder_pressed) s.x=120;
  return s;
}
function draw(s){return [
  {op:'clear',color:'#102030'},
  {op:'sprite',id:'ship',x:s.x,y:s.y,scale:2},
  {op:'text',x:4,y:4,text:String(s.score),size:12,color:'#FFFFFF'}
];}
"""


def fixture(code=GAME_CODE):
    return {"kind": "game", "title": "Runtime test", "code": code,
            "controls": ["joystick", "encoder", "button_a", "button_b", "encoder_pressed"],
            "assets": {"sprites": {"ship": {"width": 3, "height": 2,
                "palette": ["transparent", "#FF3300"], "pixels": [[0, 1, 0], [1, 1, 1]]}}}}


class PackageTests(unittest.TestCase):
    def test_normalization_copies_assets_and_controls(self):
        original = fixture()
        result = validate_package(original)
        original["assets"]["sprites"]["ship"]["pixels"][0][0] = 1
        original["controls"].clear()
        self.assertEqual(result["assets"]["sprites"]["ship"]["pixels"][0][0], 0)
        self.assertEqual(len(result["controls"]), 5)

    def test_package_limits_and_unknown_fields(self):
        cases = [("kind", "python"), ("title", ""), ("title", "\n"),
                 ("code", "x" * (MAX_CODE_BYTES + 1)), ("code", "💥" * 11000),
                 ("code", "\ud800"), ("controls", ["shell"]),
                 ("controls", ["encoder", "encoder"]), ("controls", [None]),
                 ("assets", {"sprites": {}})]
        for key, value in cases:
            with self.subTest(key=key, value=str(value)[:30]):
                package = fixture()
                package[key] = value
                with self.assertRaises(GameError):
                    validate_package(package)
        package = fixture()
        package["install"] = "curl bad"
        with self.assertRaises(GameError):
            validate_package(package)

    def test_sprite_size_palette_and_rows(self):
        cases = [("width", 33), ("height", 0), ("width", True),
                 ("palette", ["red"]), ("palette", []),
                 ("pixels", [[0, 2, 0], [1, 1, 1]]),
                 ("pixels", [[0, 1], [1, 1, 1]]),
                 ("pixels", [[0, True, 0], [1, 1, 1]])]
        for key, value in cases:
            package = fixture()
            package["assets"]["sprites"]["ship"][key] = value
            with self.subTest(key=key):
                with self.assertRaises(GameError):
                    validate_package(package)
        package = fixture()
        package["assets"]["sprites"]["ship"]["palette"] = ["transparent", "transparent"]
        with self.assertRaises(GameError):
            validate_package(package)
        package = fixture()
        sprite = {"width": 32, "height": 32, "palette": ["#FFFFFF"], "pixels": [[0]*32 for _ in range(32)]}
        package["assets"]["sprites"] = {f"sprite{i}": copy.deepcopy(sprite) for i in range(9)}
        with self.assertRaises(GameError):
            validate_package(package)

    def test_input_and_state_are_bounded(self):
        self.assertEqual(validate_input({})["joystick_x"], 0)
        for value in [{"joystick_x": 1.1}, {"joystick_x": float("nan")},
                      {"encoder_delta": 1.5}, {"button_a": 1}, {"other": 1},
                      {"joystick_y": 10**1000}]:
            with self.subTest(value=str(value)[:30]):
                with self.assertRaises(GameError):
                    validate_input(value)
        for value in [[], {"x": float("inf")}, {"x": 10**1000},
                      {"x": "x"*4097}, {"x": [0]*2049},
                      {"x": ["x"*100 for _ in range(1000)]}]:
            with self.assertRaises(GameError):
                validate_state(value)
        nested = {}
        for _ in range(18):
            nested = {"nested": nested}
        with self.assertRaises(GameError):
            validate_state(nested)

    def test_draw_contract_accepts_clipped_coordinates(self):
        sprites = fixture()["assets"]["sprites"]
        commands = [{"op":"clear","color":"#000000"},
                    {"op":"rect","x":-10,"y":20,"w":250,"h":5,"color":"#FFFFFF"},
                    {"op":"circle","x":10,"y":10,"r":3,"color":"#FFFFFF"},
                    {"op":"line","x1":0,"y1":0,"x2":240,"y2":135,"color":"#FFFFFF"},
                    {"op":"sprite","id":"ship","x":-32,"y":140,"scale":1},
                    {"op":"text","x":0,"y":0,"text":"test","size":8,"color":"#FFFFFF"}]
        self.assertEqual(validate_commands(commands, sprites), commands)
        bad = [[], [{"op":"shell","command":"bad"}],
               [{"op":"clear","color":"red"}],
               [{"op":"sprite","id":"missing","x":0,"y":0,"scale":1}],
               [{"op":"sprite","id":"ship","x":0,"y":0,"scale":999}],
               [{"op":"rect","x":float("inf"),"y":0,"w":1,"h":1,"color":"#000000"}],
               [{"op":"clear","color":"#000000","extra":1}],
               [{"op":"clear","color":"#000000"}]*129]
        for commands in bad:
            with self.subTest(commands=str(commands)[:60]):
                with self.assertRaises(GameError):
                    validate_commands(commands, sprites)


class WorkerTests(unittest.TestCase):
    def test_generated_logic_input_effect_and_persistent_state(self):
        with Game(fixture()) as game:
            initial = game.initial_frame
            pid = game._process.pid
            first = game.step({"joystick_x": 1, "button_a": True}, 1/30)
            second = game.step({"encoder_delta": -4, "joystick_y": -1}, 1/30)
            self.assertEqual(game._process.pid, pid)
            self.assertEqual(initial["state"]["x"], 120)
            self.assertEqual(first["state"], {"x":122,"y":60,"score":1})
            self.assertEqual(second["state"], {"x":118,"y":58,"score":1})
            self.assertEqual(second["commands"][1]["x"], 118)
            self.assertTrue(game.isolation["host_api_absent"])
            self.assertTrue(all(game.isolation["os_probe_results"].values()))
            self.assertFalse(game.isolation["host_callbacks"])
        with self.assertRaises(GameError):
            game.step({})

    def test_code_actually_changes_behavior(self):
        with Game(fixture()) as normal, Game(fixture(GAME_CODE.replace("*60*dt", "*120*dt"))) as faster:
            self.assertEqual(normal.step({"joystick_x":1}, .1)["state"]["x"], 126)
            self.assertEqual(faster.step({"joystick_x":1}, .1)["state"]["x"], 132)

    def test_generated_code_has_no_environment_or_host_api(self):
        code = """
        function init(){return {apis:[typeof process,typeof require,typeof std,typeof os,
          typeof fetch,typeof XMLHttpRequest,typeof WebSocket,typeof document,
          typeof console,Function('return typeof process')()]};}
        function update(s){return s;}
        function draw(){return [{op:'sprite',id:'ship',x:0,y:0,scale:1}];}
        """
        os.environ["MODULATE_TEST_SECRET"] = "not-for-worker"
        try:
            with Game(fixture(code)) as game:
                self.assertEqual(game.initial_frame["state"]["apis"], ["undefined"]*10)
        finally:
            os.environ.pop("MODULATE_TEST_SECRET", None)

    def test_draw_does_not_mutate_persisted_state(self):
        code = """function init(){return {x:1}} function update(s){s.x++;return s}
        function draw(s){s.x=99;return [{op:'sprite',id:'ship',x:s.x,y:0,scale:1}]}"""
        with Game(fixture(code)) as game:
            self.assertEqual(game.initial_frame["state"]["x"], 1)
            self.assertEqual(game.step({})["state"]["x"], 2)

    def test_time_limit_failure_closes_worker(self):
        code = GAME_CODE.replace("s.x += input", "while(true){}; s.x += input")
        game = Game(fixture(code))
        started = time.monotonic()
        with self.assertRaisesRegex(GameError, "interrupted|wall-clock"):
            game.step({})
        self.assertLess(time.monotonic()-started, 2)
        self.assertIsNone(game._process)
        game.close()

    def test_startup_cpu_memory_stack_and_bad_output(self):
        malicious = [
            "function init(){while(true){}}",
            "function init(){return {a:new ArrayBuffer(67108864)}}",
            "function init(){function f(){return f()} return f()}",
            "function init(){return {x:NaN}}",
            "function init(){return {x:undefined}}",
            "function init(){return {x:1n}}",
            "function init(){let x={};x.x=x;return x}",
            "function init(){return {get x(){while(true){}}}}",
            "async function init(){return {}}",
            "function init(){return {x:()=>1}}",
            "function init(){return {}} function draw(){return [{op:'sprite',id:'other',x:0,y:0,scale:1}]}",
            "import fs from 'fs'; function init(){return {}}",
        ]
        for code in malicious:
            prefix = "function update(s){return s} function draw(){return [{op:'clear',color:'#000000'}]}\n"
            with self.subTest(code=code):
                with self.assertRaises(GameError):
                    with Game(fixture(prefix+code)):
                        pass

    def test_verify_checks_inputs_assets_and_fixed_resource_probes(self):
        report = verify(fixture())
        self.assertTrue(report["passed"], report["errors"])
        self.assertEqual(report["metrics"]["frames"], 49)
        self.assertGreater(report["metrics"]["distinct_states"], 1)
        self.assertEqual(len(report["metrics"]["package_sha256"]), 64)
        names = {item["name"] for item in report["checks"]}
        self.assertTrue({"cpu_guard", "memory_guard", "state_guard", "command_guard", "sprite_output"} <= names)
        package = fixture(GAME_CODE.replace("op:'sprite',id:'ship',x:s.x,y:s.y,scale:2", "op:'clear',color:'#FFFFFF'"))
        report = verify(package)
        self.assertFalse(report["passed"])
        self.assertTrue(any("sprite_output" in error for error in report["errors"]))

    def test_invalid_package_report_is_bounded_failure(self):
        report = verify({})
        self.assertFalse(report["passed"])
        self.assertEqual(report["checks"][0]["name"], "package")


if __name__ == "__main__":
    unittest.main()
