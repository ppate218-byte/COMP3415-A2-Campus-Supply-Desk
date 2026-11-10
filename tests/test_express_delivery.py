"""CR-01 tests: express delivery.

Expected values come from CR-01 and FUNCTIONAL_SPEC.md, not from the code.
"""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from supplydesk import cli
from supplydesk.menu import run_menu
from supplydesk.service import OrderService

INITIAL_STOCK = {"notebook": 20, "pen-pack": 10, "hoodie": 5, "mug": 8, "bag": 4}


def item(product_id, quantity):
    return {"product_id": product_id, "quantity": quantity}


def amounts(result):
    """(subtotal, discount, delivery, total) in cents."""
    return (result["subtotal_cents"], result["discount_cents"],
            result["delivery_cents"], result["total_cents"])


class ExpressTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "state.json"
        self.service = OrderService(self.path)

    def stock(self):
        return {p["product_id"]: p["stock"] for p in self.service.catalog()}

    def assert_quote_and_order(self, customer, items, expected):
        quote = self.service.quote(customer, items, "express")
        order = self.service.place_order(customer, items, "express")
        with self.subTest(operation="quote"):
            self.assertEqual(amounts(quote), expected)
        with self.subTest(operation="place_order"):
            self.assertEqual(amounts(order), expected)


class ExpressPricingTests(ExpressTestCase):
    def test_regular_two_notebooks_express(self):
        # CR-01 example: $10 + $12 = $22.
        self.assert_quote_and_order("regular", [item("notebook", 2)],
                                    (1000, 0, 1200, 2200))

    def test_student_two_hoodies_express(self):
        # CR-01 example: $80 - $8 + $12 = $84.
        self.assert_quote_and_order("student", [item("hoodie", 2)],
                                    (8000, 800, 1200, 8400))

    def test_three_hoodies_standard_versus_express(self):
        # CR-01 example: standard $120, express $132.
        items = [item("hoodie", 3)]
        standard = self.service.quote("regular", items, "delivery")
        express = self.service.quote("regular", items, "express")
        self.assertEqual(amounts(standard), (12000, 0, 0, 12000))
        self.assertEqual(amounts(express), (12000, 0, 1200, 13200))

    def test_express_fee_never_waived_above_free_threshold(self):
        # 20 notebooks = 10,000: standard delivery would be free.
        self.assert_quote_and_order("regular", [item("notebook", 20)],
                                    (10000, 0, 1200, 11200))

    def test_student_discount_applies_to_merchandise_only(self):
        # 11 notebooks = 5,500; discount 550; delivery fee untouched.
        self.assert_quote_and_order("student", [item("notebook", 11)],
                                    (5500, 550, 1200, 6150))

    def test_student_below_discount_threshold_pays_no_discount(self):
        self.assert_quote_and_order("student", [item("notebook", 9)],
                                    (4500, 0, 1200, 5700))

    def test_student_express_fee_not_reduced_by_discount(self):
        # Subtotal 10,000, discount 1,000: fee stays 1,200.
        self.assert_quote_and_order("student", [item("notebook", 20)],
                                    (10000, 1000, 1200, 10200))


class ExistingFulfillmentUnchangedTests(ExpressTestCase):
    def test_pickup_unchanged(self):
        quote = self.service.quote("regular", [item("notebook", 2)], "pickup")
        self.assertEqual(amounts(quote), (1000, 0, 0, 1000))

    def test_standard_delivery_fee_below_threshold_unchanged(self):
        quote = self.service.quote("regular", [item("notebook", 19)], "delivery")
        self.assertEqual(amounts(quote), (9500, 0, 600, 10100))

    def test_standard_delivery_free_at_threshold_unchanged(self):
        quote = self.service.quote("regular", [item("notebook", 20)], "delivery")
        self.assertEqual(amounts(quote), (10000, 0, 0, 10000))


class ExpressOrderLifecycleTests(ExpressTestCase):
    def test_quote_matches_placed_order(self):
        items = [item("hoodie", 1), item("mug", 1)]
        quote = self.service.quote("student", items, "express")
        order = self.service.place_order("student", items, "express")
        for key, value in quote.items():
            with self.subTest(field=key):
                self.assertEqual(order[key], value)

    def test_placement_deducts_stock_and_numbers_order(self):
        order = self.service.place_order("regular", [item("notebook", 3)], "express")
        self.assertEqual(order["order_id"], "ORD-0001")
        self.assertEqual(order["status"], "placed")
        self.assertEqual(self.stock(), dict(INITIAL_STOCK, notebook=17))

    def test_express_quote_does_not_change_stock_or_create_file(self):
        self.service.quote("regular", [item("hoodie", 2)], "express")
        self.assertFalse(self.path.exists())
        self.assertEqual(self.stock(), INITIAL_STOCK)

    def test_express_order_retained_on_retrieval_reopen_and_cancel(self):
        placed = self.service.place_order(
            "student", [item("hoodie", 2), item("mug", 1)], "express")
        expected = amounts(placed)
        self.assertEqual(expected, (9500, 950, 1200, 9750))
        with self.subTest(stage="retrieved"):
            fetched = self.service.get_order(placed["order_id"])
            self.assertEqual(fetched["fulfillment"], "express")
            self.assertEqual(amounts(fetched), expected)
        with self.subTest(stage="reopened"):
            reopened = OrderService(self.path)
            fetched = reopened.get_order(placed["order_id"])
            self.assertEqual(fetched["fulfillment"], "express")
            self.assertEqual(fetched["items"], placed["items"])
            self.assertEqual(amounts(fetched), expected)
        with self.subTest(stage="cancelled"):
            cancelled = OrderService(self.path).cancel_order(placed["order_id"])
            self.assertEqual(cancelled["status"], "cancelled")
            self.assertEqual(cancelled["fulfillment"], "express")
            self.assertEqual(cancelled["items"], placed["items"])
            self.assertEqual(amounts(cancelled), expected)
            self.assertEqual(self.stock(), INITIAL_STOCK)


class FulfillmentValidationTests(ExpressTestCase):
    def test_other_fulfillment_values_remain_invalid(self):
        for value in ("shipping", "overnight", "Express", "EXPRESS",
                      " express", "express ", "", None):
            for operation in ("quote", "place_order"):
                with self.subTest(value=value, operation=operation):
                    with self.assertRaises(ValueError):
                        getattr(self.service, operation)(
                            "regular", [item("notebook", 1)], value)
        self.assertFalse(self.path.exists())
        self.assertEqual(self.stock(), INITIAL_STOCK)


def run_cli(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(argv)
    return code, out.getvalue(), err.getvalue()


class ExpressCliTests(ExpressTestCase):
    def test_cli_quote_express_matches_cr_example(self):
        code, out, _ = run_cli(["--data", str(self.path), "quote", "--customer",
                                "student", "--fulfillment", "express",
                                "--item", "hoodie:2"])
        self.assertEqual(code, 0)
        result = json.loads(out)
        self.assertEqual(result["fulfillment"], "express")
        self.assertEqual(result["delivery_cents"], 1200)
        self.assertEqual(result["total_cents"], 8400)

    def test_cli_place_then_show_keeps_express(self):
        code, _, _ = run_cli(["--data", str(self.path), "place", "--fulfillment",
                              "express", "--item", "notebook:2"])
        self.assertEqual(code, 0)
        code, out, _ = run_cli(["--data", str(self.path), "show", "ORD-0001"])
        self.assertEqual(code, 0)
        shown = json.loads(out)
        self.assertEqual(shown["fulfillment"], "express")
        self.assertEqual(shown["total_cents"], 2200)

    def test_cli_default_fulfillment_still_pickup(self):
        code, out, _ = run_cli(["--data", str(self.path), "quote",
                                "--item", "notebook:2"])
        self.assertEqual(code, 0)
        result = json.loads(out)
        self.assertEqual(result["fulfillment"], "pickup")
        self.assertEqual(result["total_cents"], 1000)

    def test_cli_rejects_other_fulfillment_values(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as caught:
                cli.main(["--data", str(self.path), "quote", "--fulfillment",
                          "shipping", "--item", "notebook:1"])
        self.assertEqual(caught.exception.code, 2)

    def test_cli_help_mentions_express(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            with self.assertRaises(SystemExit):
                cli.main(["quote", "--help"])
        self.assertIn("express", out.getvalue())


def run_menu_session(path, inputs):
    queue = list(inputs)

    def fake_input(prompt=""):
        print(prompt, end="")
        if not queue:
            raise EOFError
        return queue.pop(0)

    out = io.StringIO()
    with patch("builtins.input", fake_input), contextlib.redirect_stdout(out):
        run_menu(OrderService(path))
    return out.getvalue()


class ExpressMenuTests(ExpressTestCase):
    def test_menu_quote_express(self):
        text = run_menu_session(self.path, ["2", "student", "hoodie", "2", "",
                                            "express", "0"])
        self.assertIn("Fulfillment: express", text)
        self.assertIn("Delivery: $12.00", text)
        self.assertIn("Total: $84.00", text)

    def test_menu_fulfillment_prompt_mentions_express(self):
        text = run_menu_session(self.path, ["2", "", "notebook", "2", "", "", "0"])
        prompts = [line for line in text.splitlines() if "Fulfillment [" in line]
        self.assertTrue(prompts)
        self.assertIn("express", prompts[0])

    def test_menu_defaults_unchanged(self):
        text = run_menu_session(self.path, ["2", "", "notebook", "2", "", "", "0"])
        self.assertIn("Customer: regular | Fulfillment: pickup", text)
        self.assertIn("Total: $10.00", text)


if __name__ == "__main__":
    unittest.main()
