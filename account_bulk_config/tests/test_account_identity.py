"""Pure tests for matching an account across companies with the same chart."""

from unittest import TestCase

from account_bulk_config.api.account_identity import match_accounts, swap_company_suffix


def acc(name, account_name, number=None, parent=None, group=0):
	return {
		"name": name,
		"account_name": account_name,
		"account_number": number,
		"parent_account": parent,
		"is_group": group,
	}


def matched(source, target):
	return match_accounts(source, target, "SRC", "TGT")[0]


class TestAccountIdentity(TestCase):
	def test_suffix_swap_only_replaces_the_whole_company_token(self):
		self.assertEqual(swap_company_suffix("1000 - Kas - JG", "JG", "A"), "1000 - Kas - A")
		self.assertIsNone(swap_company_suffix("1000 - Kas - A", "JG", "A"))
		# JURIGROUP ends with " - JURIGROUP", not with " - JURI"
		self.assertIsNone(swap_company_suffix("1000 - Kas - JURIGROUP", "JURI", "A"))

	def test_exact_copy_wins_over_a_duplicate_name(self):
		source = [acc("1131.000 - Piutang Dagang - SRC", "Piutang Dagang", "1131.000")]
		target = [
			acc("1131.0010 - Piutang Dagang - TGT", "Piutang Dagang", "1131.0010"),
			acc("1131.000 - Piutang Dagang - TGT", "Piutang Dagang", "1131.000"),
		]

		[copy] = matched(source, target).values()

		self.assertEqual(copy["name"], "1131.000 - Piutang Dagang - TGT")

	def test_number_matches_a_copy_renamed_in_the_parent(self):
		source = [acc("5230.001 - Biaya PLN - SRC", "Biaya PLN", "5230.001")]
		target = [acc("5230.001 - Biaya Listrik - TGT", "Biaya Listrik", "5230.001")]

		[copy] = matched(source, target).values()

		self.assertEqual(copy["name"], "5230.001 - Biaya Listrik - TGT")

	def test_duplicate_names_with_different_numbers_match_their_number(self):
		source = [
			acc("S1 - SRC", "Biaya BBM", "5110.001"),
			acc("S2 - SRC", "Biaya BBM", "5220.001"),
		]
		target = [
			acc("T2 - TGT", "Biaya BBM", "5220.001"),
			acc("T1 - TGT", "Biaya BBM", "5110.001"),
		]

		matches = matched(source, target)

		self.assertEqual(matches["S1 - SRC"]["name"], "T1 - TGT")
		self.assertEqual(matches["S2 - SRC"]["name"], "T2 - TGT")

	def test_unique_name_matches_when_there_is_no_number(self):
		source = [acc("A - SRC", "Kas Kecil")]
		target = [acc("B - TGT", "Kas Kecil")]

		[copy] = matched(source, target).values()

		self.assertEqual(copy["name"], "B - TGT")

	def test_parent_decides_between_duplicate_names_without_numbers(self):
		source = [
			acc("SA - SRC", "Group A", None, "Root - SRC", group=1),
			acc("SB - SRC", "Group B", None, "Root - SRC", group=1),
			acc("P - SRC", "Kembar", None, "SA - SRC"),
			acc("Q - SRC", "Kembar", None, "SB - SRC"),
		]
		target = [
			acc("GA - TGT", "Group A", None, "Root - TGT", group=1),
			acc("GB - TGT", "Group B", None, "Root - TGT", group=1),
			acc("Y - TGT", "Kembar", None, "GB - TGT"),
			acc("X - TGT", "Kembar", None, "GA - TGT"),
		]

		matches = matched(source, target)

		self.assertEqual(matches["P - SRC"]["name"], "X - TGT")
		self.assertEqual(matches["Q - SRC"]["name"], "Y - TGT")

	def test_ambiguous_name_without_a_matched_parent_is_reported(self):
		source = [acc("S - SRC", "Kembar", None, "Missing - SRC")]
		target = [
			acc("X - TGT", "Kembar", None, "Other - TGT"),
			acc("Y - TGT", "Kembar", None, "Other 2 - TGT"),
		]

		matches, ambiguous = match_accounts(source, target, "SRC", "TGT")

		self.assertEqual(matches, {})
		self.assertEqual(ambiguous, {"S - SRC": {"X - TGT", "Y - TGT"}})

	def test_a_name_absent_from_the_target_is_left_for_creation(self):
		source = [acc("S - SRC", "Baru")]
		target = [acc("T - TGT", "Lain")]

		matches, ambiguous = match_accounts(source, target, "SRC", "TGT")

		self.assertEqual(matches, {})
		self.assertEqual(ambiguous, {})

	def test_case_only_document_and_name_difference_matches_the_same_account(self):
		source = [acc("sales - SRC", "sales", None, "P - SRC")]
		target = [acc("Sales - TGT", "Sales", None, "P - TGT")]

		matches, ambiguous = match_accounts(source, target, "SRC", "TGT")

		self.assertEqual(matches["sales - SRC"]["name"], "Sales - TGT")
		self.assertEqual(ambiguous, {})

	def test_ambiguity_protects_only_the_matched_parent_branch(self):
		source = [
			acc("P - SRC", "P", None, None, group=1),
			acc("S - SRC", "Penjualan", None, "P - SRC"),
		]
		target = [
			acc("P - TGT", "P", None, None, group=1),
			acc("Q - TGT", "Q", None, None, group=1),
			acc("T1 - TGT", "Penjualan", None, "P - TGT"),
			acc("T2 - TGT", "Penjualan", None, "P - TGT"),
			acc("T3 - TGT", "Penjualan", None, "Q - TGT"),
		]

		matches, ambiguous = match_accounts(source, target, "SRC", "TGT")

		self.assertEqual(matches["P - SRC"]["name"], "P - TGT")
		self.assertEqual(ambiguous, {"S - SRC": {"T1 - TGT", "T2 - TGT"}})

	def test_two_same_named_sources_under_one_parent_do_not_take_one_candidate(self):
		source = [
			acc("P - SRC", "P", None, None, group=1),
			acc("S10 - SRC", "Penjualan", "10", "P - SRC"),
			acc("S20 - SRC", "Penjualan", "20", "P - SRC"),
		]
		target = [
			acc("P - TGT", "P", None, None, group=1),
			acc("T30 - TGT", "Penjualan", "30", "P - TGT"),
		]

		matches, ambiguous = match_accounts(source, target, "SRC", "TGT")

		self.assertEqual(matches["P - SRC"]["name"], "P - TGT")
		self.assertEqual(
			ambiguous,
			{"S10 - SRC": {"T30 - TGT"}, "S20 - SRC": {"T30 - TGT"}},
		)

	def test_a_root_never_pairs_with_a_nested_account(self):
		source = [acc("1000 - Aktiva - SRC", "Aktiva", "1000", None, group=1)]
		target = [acc("1210 - Aktiva - TGT", "Aktiva", "1210", "1200 - X - TGT", group=1)]

		self.assertEqual(matched(source, target), {})
