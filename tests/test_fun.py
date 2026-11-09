from __future__ import annotations

import unittest
from unittest.mock import patch

from cogs.fun import parse_choice_options, roll_dice


class FunCommandHelperTests(unittest.TestCase):
    def test_choice_parser_keeps_trimmed_options_and_rejects_bad_lists(self) -> None:
        self.assertEqual(parse_choice_options(" tea | coffee | water "), ["tea", "coffee", "water"])
        for value in ("", "only one", "| |", "|".join(str(index) for index in range(26))):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    parse_choice_options(value)

    def test_dice_rolls_are_bounded_and_use_requested_sides(self) -> None:
        with patch("cogs.fun.random.randint", return_value=4) as randint:
            self.assertEqual(roll_dice(3, 8), [4, 4, 4])
        self.assertEqual(randint.call_count, 3)
        for count, sides in ((0, 6), (21, 6), (1, 1), (1, 1001)):
            with self.subTest(count=count, sides=sides):
                with self.assertRaises(ValueError):
                    roll_dice(count, sides)


if __name__ == "__main__":
    unittest.main()
