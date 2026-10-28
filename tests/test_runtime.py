import unittest
from unittest.mock import patch

from modulate.runtime import Frame, ValidationError, run, validate


class RuntimeTests(unittest.TestCase):
    def test_numeric_program_and_frame_contract(self):
        source = """value = randint(1, 6)
if value >= 4:
    value = max(value * 2, 10)
else:
    value = min(abs(-value) + 1, 3)
show(value, label='Roll', foreground='#12aBcF', background='#000000')
"""
        self.assertIsNone(validate(source))
        with patch("modulate.runtime._RNG") as rng:
            rng.randint.return_value = 5
            frame = run(source)
            rng.randint.assert_called_once_with(1, 6)
        self.assertEqual(frame.as_dict(), {
            "number": 10, "label": "Roll", "foreground": "#12aBcF", "background": "#000000",
        })
        with patch("modulate.runtime._RNG") as rng:
            rng.randint.return_value = 1
            self.assertEqual(run(source).number, 2)

    def test_integer_operations_and_comparisons(self):
        cases = {
            "show(7 // 3)": 2,
            "show(-7 // 3)": -3,
            "show(-7 % 3)": 2,
            "show(+7 - 2 * 3)": 1,
            "show(abs(-999999))": 999999,
        }
        for source, expected in cases.items():
            with self.subTest(source=source):
                self.assertEqual(run(source).number, expected)
        for comparison in ["1 == 1", "1 != 2", "1 < 2", "1 <= 1", "2 > 1", "2 >= 2", "0 < 1 < 2"]:
            with self.subTest(comparison=comparison):
                self.assertEqual(run(f"x = 0\nif {comparison}:\n    x = 1\nshow(x)").number, 1)

    def test_defaults_and_signed_screen_edges(self):
        self.assertEqual(run("show(0)"), Frame(0))
        self.assertEqual(run("show(-999999)").number, -999999)
        self.assertEqual(run("show(999999)").number, 999999)
        self.assertEqual(run("show(1, label='ABCDEFGHIJKLMNOPQRSTUVWX')").label, "ABCDEFGHIJKLMNOPQRSTUVWX")

    def test_forbidden_syntax_including_inactive_branches(self):
        hostile = [
            "import os\nshow(0)",
            "from os import system\nshow(0)",
            "show(__import__('os'))",
            "show((1).__class__)",
            "x = [1]\nshow(x[0])",
            "x = [v for v in (1, 2)]\nshow(0)",
            "x = f'{1}'\nshow(0)",
            "x = lambda: 1\nshow(0)",
            "while 1 == 1:\n    x = 1\nshow(0)",
            "for x in range(3):\n    x = 1\nshow(0)",
            "def f():\n    return 1\nshow(0)",
            "class X:\n    pass\nshow(0)",
            "x = open('/tmp/file')\nshow(0)",
            "x = eval('1')\nshow(0)",
            "x = exec('print(1)')\nshow(0)",
            "x = (y := 1)\nshow(x)",
            "x = 1 if 1 == 1 else 2\nshow(x)",
            "x = 2 ** 30\nshow(x)",
            "x = 1 << 2\nshow(x)",
            "x = 1 / 2\nshow(x)",
            "x = ~1\nshow(x)",
            "x = True\nshow(x)",
            "x = 1.5\nshow(x)",
            "x = '1'\nshow(x)",
            "x: int = 1\nshow(x)",
            "x = 1\nx += 1\nshow(x)",
            "x = y = 1\nshow(x)",
            "x, y = 1, 2\nshow(x)",
            "__x = 1\nshow(__x)",
            "x__y = 1\nshow(x__y)",
            "randint = 1\nshow(randint)",
            "show = 1\nshow(0)",
            "K = 1\nshow(K)",
            "if 1:\n    x = 1\nshow(0)",
            "if 1 == 1 and 2 == 2:\n    x = 1\nshow(0)",
            "if 1 is 1:\n    x = 1\nshow(0)",
            "if 1 == 0:\n    import os\nshow(0)",
            "if 1 == 0:\n    x = (1).__class__\nshow(0)",
            "if 1 == 0:\n    x = 1000000001\nshow(0)",
        ]
        for source in hostile:
            with self.subTest(source=source):
                with self.assertRaises(ValidationError):
                    validate(source)

    def test_exactly_one_final_top_level_show(self):
        invalid = ["", "x = 1", "show(1)\nshow(2)", "show(1)\nx = 2",
                   "if 1 == 1:\n    show(1)", "if 1 == 0:\n    show(2)\nshow(1)",
                   "x = show(1)\nshow(x)", "show(show(1))", "show()", "show(1, 2)",
                   "show(number=1)", "show(*[1])", "show(1, **{})"]
        for source in invalid:
            with self.subTest(source=source):
                with self.assertRaises(ValidationError):
                    validate(source)

    def test_names_must_be_assigned_on_all_paths(self):
        for source in ["show(missing)", "x = x + 1\nshow(x)",
                       "if 1 == 1:\n    x = 1\nshow(x)",
                       "if 1 == 0:\n    x = missing\nshow(0)"]:
            with self.subTest(source=source):
                with self.assertRaises(ValidationError):
                    validate(source)
        self.assertEqual(run("if 1 == 1:\n    x = 2\nelse:\n    x = 3\nshow(x)").number, 2)

    def test_numeric_function_signatures(self):
        for expression in ["randint(1)", "randint(1, 2, 3)", "randint(low=1, high=2)",
                           "abs()", "abs(1, 2)", "min(1)", "max()", "min(*[1, 2])",
                           "max(1,2,3,4,5,6,7,8,9)"]:
            with self.subTest(expression=expression):
                with self.assertRaises(ValidationError):
                    validate(f"show({expression})")

    def test_arithmetic_and_output_bounds(self):
        invalid = ["show(1000000)", "show(-1000000)", "show(1 // 0)", "show(1 % 0)",
                   "x = 1000000000 + 1\nshow(0)", "x = -1000000000 - 1\nshow(0)",
                   "x = 1000000000 * 1000000000\nshow(0)",
                   "show((1000000000 * 2) // 1000000000)",
                   "show(randint(2, 1))", "show(randint(-1000000000, 1000000000))",
                   "show(randint(0, 1000000001))"]
        for source in invalid:
            with self.subTest(source=source):
                with self.assertRaises(ValidationError):
                    run(source)
        self.assertEqual(run("x = 1000000000\nshow(x // 1000000000)").number, 1)
        self.assertEqual(run("show(randint(2, 2))").number, 2)

    def test_display_style_bounds(self):
        invalid = ["label='ABCDEFGHIJKLMNOPQRSTUVWXY'", "label='line\\nfeed'",
                   "label='tab\\t'", "label='\\x7f'", "label='\\u00e9'", "label=1",
                   "label=str(1)", "foreground='red'", "foreground='#12345G'",
                   "foreground='#fff'", "background='#00000000'", "background=0",
                   "label='a', label='b'", "other='x'"]
        for keyword in invalid:
            with self.subTest(keyword=keyword):
                with self.assertRaises(ValidationError):
                    validate(f"show(1, {keyword})")

    def test_program_size_depth_and_operation_budgets(self):
        invalid = [None, b"show(0)", "#" * 6001, "show(1", "show(0)\x00",
                   "x = 1\n" * 100 + "show(x)",
                   "show(" + "+" * 40 + "1)",
                   "show(" + "(" * 250 + "1" + ")" * 250 + ")"]
        for source in invalid:
            with self.subTest(source=str(source)[:50]):
                with self.assertRaises(ValidationError):
                    validate(source)
        self.assertEqual(run("x = 1\n" * 99 + "show(x)").number, 1)
        # Even never-taken statements consume the static budget.
        source = "if 1 == 0:\n" + "    x = 1\n" * 100 + "show(0)"
        with self.assertRaises(ValidationError):
            validate(source)

    def test_validation_does_not_call_rng_or_execute_program(self):
        with patch("modulate.runtime._RNG") as rng:
            validate("show(randint(1, 6))")
            rng.randint.assert_not_called()


if __name__ == "__main__":
    unittest.main()
