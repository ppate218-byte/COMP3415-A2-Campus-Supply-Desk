"""Task 2 Safety net tests for Order Service."""
import tempfile
import unittest
from pathlib import Path

from supplydesk.service import OrderService

# Initial stock from FUNCTIONAL_SPEC.md (Catalog section).
INITIAL_STOCK = {"notebook": 20, "pen-pack": 10, "hoodie": 5, "mug": 8, "bag": 4}


def item(product_id, quantity):
    return {"product_id": product_id, "quantity": quantity}


def amounts(result):
    """(subtotal, discount, delivery, total) in cents."""
    return (
        result["subtotal_cents"],
        result["discount_cents"],
        result["delivery_cents"],
        result["total_cents"],
    )


class ServiceTestCase(unittest.TestCase):
    """Gives every test its own temporary save file."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "state.json"
        self.service = OrderService(self.path)

    def stock(self):
        return {p["product_id"]: p["stock"] for p in self.service.catalog()}

    def assert_pricing(self, customer, items, fulfillment, expected):
        """Spec: pricing rules apply identically to quotes and placed orders."""
        quote = self.service.quote(customer, items, fulfillment)
        order = self.service.place_order(customer, items, fulfillment)
        with self.subTest(operation="quote"):
            self.assertEqual(amounts(quote), expected)
        with self.subTest(operation="place_order"):
            self.assertEqual(amounts(order), expected)


class NormalBehaviourTests(ServiceTestCase):
    """Category 1: normal behaviour."""

    def test_multi_product_order_total_and_stock(self):
        order = self.service.place_order(
            "regular", [item("notebook", 3), item("mug", 1)]
        )
        self.assertEqual(order["order_id"], "ORD-0001")
        self.assertEqual(order["status"], "placed")
        self.assertEqual(amounts(order), (3000, 0, 0, 3000))
        self.assertEqual(self.stock(), dict(INITIAL_STOCK, notebook=17, mug=7))

    def test_regular_delivery_three_hoodies_is_free_delivery(self):
        # Spec example: subtotal 12,000; discount 0; delivery 0; total 12,000.
        self.assert_pricing("regular", [item("hoodie", 3)], "delivery",
                            (12000, 0, 0, 12000))

    def test_order_ids_increase_and_history_keeps_placement_order(self):
        first = self.service.place_order("regular", [item("notebook", 1)])
        second = self.service.place_order("regular", [item("mug", 1)])
        self.assertEqual([first["order_id"], second["order_id"]],
                         ["ORD-0001", "ORD-0002"])
        ids = [o["order_id"] for o in self.service.list_orders()]
        self.assertEqual(ids, ["ORD-0001", "ORD-0002"])


class BoundaryBehaviourTests(ServiceTestCase):
    """Category 2: boundary behaviour."""

    def test_student_just_below_discount_threshold(self):
        # 9 notebooks = 4,500 cents (< 5,000): no discount.
        self.assert_pricing("student", [item("notebook", 9)], "pickup",
                            (4500, 0, 0, 4500))

    def test_student_discount_at_exact_threshold(self):
        # Spec: discount when subtotal is AT LEAST 5,000. 10 notebooks = 5,000.
        self.assert_pricing("student", [item("notebook", 10)], "pickup",
                            (5000, 500, 0, 4500))

    def test_student_discount_just_above_threshold(self):
        # 11 notebooks = 5,500; discount 550.
        self.assert_pricing("student", [item("notebook", 11)], "pickup",
                            (5500, 550, 0, 4950))

    def test_regular_customer_never_gets_discount(self):
        self.assert_pricing("regular", [item("notebook", 20)], "pickup",
                            (10000, 0, 0, 10000))

    def test_delivery_fee_just_below_free_threshold(self):
        # 19 notebooks = 9,500 (< 10,000): delivery 600.
        self.assert_pricing("regular", [item("notebook", 19)], "delivery",
                            (9500, 0, 600, 10100))

    def test_delivery_free_at_exact_threshold(self):
        # 20 notebooks = 10,000 (>= 10,000): delivery free.
        self.assert_pricing("regular", [item("notebook", 20)], "delivery",
                            (10000, 0, 0, 10000))

    def test_free_delivery_uses_subtotal_after_discount(self):
        # Student, 20 notebooks: subtotal 10,000, discount 1,000, so the
        # discounted amount 9,000 is below 10,000 and delivery is charged.
        self.assert_pricing("student", [item("notebook", 20)], "delivery",
                            (10000, 1000, 600, 9600))

    def test_order_exactly_available_stock_then_one_more_fails(self):
        order = self.service.place_order("regular", [item("bag", 4)])
        self.assertEqual(order["total_cents"], 10000)
        self.assertEqual(self.stock()["bag"], 0)
        with self.assertRaises(ValueError):
            self.service.place_order("regular", [item("bag", 1)])
        self.assertEqual(self.stock()["bag"], 0)


class InvalidBehaviourTests(ServiceTestCase):
    """Category 3: invalid or exceptional behaviour."""

    BAD_QUANTITIES = [0, -1, 100, True, 2.0, "2", None]

    def test_invalid_quantities_rejected_without_changes(self):
        for quantity in self.BAD_QUANTITIES:
            for operation in ("quote", "place_order"):
                with self.subTest(quantity=quantity, operation=operation):
                    with self.assertRaises(ValueError):
                        getattr(self.service, operation)(
                            "regular", [item("notebook", quantity)]
                        )
        self.assertFalse(self.path.exists())
        self.assertEqual(self.stock(), INITIAL_STOCK)

    def test_invalid_requests_rejected_without_changes(self):
        good = [item("notebook", 1)]
        bad_requests = {
            "unknown product": ("regular", [item("laptop", 1)], "pickup"),
            "empty items": ("regular", [], "pickup"),
            "items is None": ("regular", None, "pickup"),
            "item not a dict": ("regular", ["notebook"], "pickup"),
            "missing quantity": ("regular", [{"product_id": "notebook"}], "pickup"),
            "unknown customer type": ("staff", good, "pickup"),
            "wrong-case customer type": ("Student", good, "pickup"),
            "unknown fulfillment": ("regular", good, "shipping"),
        }
        for label, args in bad_requests.items():
            for operation in ("quote", "place_order"):
                with self.subTest(case=label, operation=operation):
                    with self.assertRaises(ValueError):
                        getattr(self.service, operation)(*args)
        self.assertFalse(self.path.exists())
        self.assertEqual(self.stock(), INITIAL_STOCK)

    def test_order_exceeding_stock_rejected(self):
        with self.assertRaises(ValueError):
            self.service.place_order("regular", [item("bag", 5)])
        self.assertEqual(self.stock(), INITIAL_STOCK)

    def test_quote_rejects_duplicate_lines_exceeding_stock(self):
        # Spec: combined quantity across duplicate lines must fit stock.
        # hoodie stock is 5; 3 + 3 = 6.
        with self.assertRaises(ValueError):
            self.service.quote("regular", [item("hoodie", 3), item("hoodie", 3)])

    def test_place_order_rejects_duplicate_lines_exceeding_stock(self):
        with self.assertRaises(ValueError):
            self.service.place_order(
                "regular", [item("hoodie", 3), item("hoodie", 3)]
            )
        self.assertEqual(self.stock(), INITIAL_STOCK)
        self.assertEqual(self.service.list_orders(), [])

    def test_failed_placement_does_not_consume_order_number(self):
        first = self.service.place_order("regular", [item("notebook", 1)])
        with self.assertRaises(ValueError):
            self.service.place_order("regular", [item("notebook", 0)])
        second = self.service.place_order("regular", [item("notebook", 1)])
        self.assertEqual([first["order_id"], second["order_id"]],
                         ["ORD-0001", "ORD-0002"])
        self.assertEqual(self.stock()["notebook"], 18)

    def test_unknown_order_id_raises_value_error(self):
        with self.assertRaises(ValueError):
            self.service.get_order("ORD-9999")
        with self.assertRaises(ValueError):
            self.service.cancel_order("ORD-9999")
        self.assertFalse(self.path.exists())


class PreserveBehaviourTests(ServiceTestCase):
    """Category 4: behaviour that must survive refactoring."""

    def test_quote_does_not_change_stock_or_create_save_file(self):
        self.service.quote("student", [item("hoodie", 2), item("mug", 1)], "delivery")
        self.assertFalse(self.path.exists())
        self.assertEqual(self.stock(), INITIAL_STOCK)

    def test_quote_matches_subsequent_placed_order(self):
        items = [item("hoodie", 1), item("mug", 1)]
        quote = self.service.quote("student", items, "delivery")
        order = self.service.place_order("student", items, "delivery")
        for key, value in quote.items():
            with self.subTest(field=key):
                self.assertEqual(order[key], value)

    def test_history_and_stock_persist_after_reopening(self):
        placed = self.service.place_order(
            "student", [item("hoodie", 2), item("mug", 1)], "delivery"
        )
        reopened = OrderService(self.path)
        self.assertEqual(reopened.list_orders(), [placed])
        self.assertEqual(
            {p["product_id"]: p["stock"] for p in reopened.catalog()},
            dict(INITIAL_STOCK, hoodie=3, mug=7),
        )

    def test_cancelling_twice_restores_stock_only_once(self):
        # Spec: cancelling an already cancelled order changes nothing.
        order = self.service.place_order("regular", [item("pen-pack", 2)])
        self.service.cancel_order(order["order_id"])
        again = self.service.cancel_order(order["order_id"])
        self.assertEqual(again["status"], "cancelled")
        self.assertEqual(self.stock(), INITIAL_STOCK)

    def test_cancelled_order_stays_in_history_and_id_not_reused(self):
        first = self.service.place_order("regular", [item("notebook", 2)])
        self.service.place_order("regular", [item("mug", 1)])
        self.service.cancel_order(first["order_id"])
        orders = self.service.list_orders()
        self.assertEqual([o["order_id"] for o in orders], ["ORD-0001", "ORD-0002"])
        self.assertEqual([o["status"] for o in orders], ["cancelled", "placed"])
        self.assertEqual(self.service.get_order("ORD-0001")["total_cents"], 1000)
        third = self.service.place_order("regular", [item("bag", 1)])
        self.assertEqual(third["order_id"], "ORD-0003")


if __name__ == "__main__":
    unittest.main()