import unittest

from app import apply_case_jar_logic, is_jar_item


class IsJarItemTests(unittest.TestCase):
    def test_20_ltr_products_with_trailing_invoice_text_are_jars(self):
        for description in ("Bisleri Water 20LTR 01 (MRP 100)",):
            with self.subTest(description=description):
                self.assertTrue(is_jar_item(description))

    def test_non_jar_sizes_and_embedded_larger_sizes_are_cases(self):
        for description in (
            "Bisleri Water 10LTR 09 (MRP 270)",
            "Bisleri Water 2LTR 09",
            "Bisleri Water 1LTR 12",
            "110LTR",
            "120LTR",
        ):
            with self.subTest(description=description):
                self.assertFalse(is_jar_item(description))

    def test_invoice_totals_only_20_ltr_quantity_as_jar(self):
        record = {
            "Invoice No.": "MUMCIN270012687",
            "items": [
                {"description": "Bisleri Water 200ML 48 (MRP 240)", "qty": 15},
                {"description": "Bisleri Water 500ML 24 (MRP 240)", "qty": 10},
                {"description": "Bisleri Water 10 LTR 09 (MRP 270)", "qty": 5},
                {"description": "Bisleri Water 5LTR 01 (MRP 75)", "qty": 20},
                {"description": "Bisleri Water 20LTR 01 (MRP 100)", "qty": 120},
            ],
        }

        processed = apply_case_jar_logic(record)

        self.assertEqual(processed["Case"], 50)
        self.assertEqual(processed["Jar"], 120)


if __name__ == "__main__":
    unittest.main()
