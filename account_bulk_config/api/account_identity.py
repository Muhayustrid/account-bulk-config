"""Stable identity of an Account across the companies that share a chart of accounts."""

from frappe.utils import cstr


def swap_company_suffix(name: str, src_abbr: str | None, dst_abbr: str | None) -> str | None:
	"""Replace the trailing ' - <src_abbr>' with ' - <dst_abbr>'; None if it cannot be mapped."""
	if not src_abbr or not dst_abbr:
		return None
	suffix = f" - {src_abbr}"
	if not name.endswith(suffix):
		return None
	return f"{name[: -len(suffix)]} - {dst_abbr}"


def _number(acc: dict) -> str:
	return cstr(acc.get("account_number")).strip()


def _is_root(acc: dict) -> bool:
	return not acc.get("parent_account")


def _compatible(src: dict, cand: dict) -> bool:
	# ERPNext refuses to move or rename a root; never pair one with a nested account
	return _is_root(src) == _is_root(cand)


def match_accounts(source: list[dict], target: list[dict], src_abbr: str, dst_abbr: str) -> tuple[dict, set]:
	"""Source account name -> its copy in the target company, each target account used once.

	Identity, strongest first:
	1. the doc name with the company suffix swapped: the copy ERPNext itself creates;
	2. account_number: unique per company;
	3. account_name, when exactly one account on each side still has it;
	4. account_name plus the already matched parent, when that narrows it to one.

	Returns (matches, ambiguous). An ambiguous name had candidates but could not be
	narrowed to one; the caller reports it instead of creating a duplicate.
	"""
	by_doc = {}
	for acc in target:
		by_doc.setdefault(acc["name"].casefold(), []).append(acc)
	by_number = {}
	for acc in target:
		number = _number(acc).casefold()
		if number:
			by_number.setdefault(number, []).append(acc)

	matches, taken = {}, set()

	def one(candidates):
		return candidates[0] if candidates and len(candidates) == 1 else None

	def take(src, cand):
		if not cand or cand["name"] in taken or not _compatible(src, cand):
			return False
		taken.add(cand["name"])
		matches[src["name"]] = cand
		return True

	pending = []
	for src in source:
		wanted = swap_company_suffix(src["name"], src_abbr, dst_abbr)
		candidate = one(by_doc.get(wanted.casefold())) if wanted else None
		if not (candidate and take(src, candidate)):
			pending.append(src)

	rest = []
	for src in pending:
		candidate = one(by_number.get(_number(src).casefold())) if _number(src) else None
		if not (candidate and take(src, candidate)):
			rest.append(src)

	# only a name that is unique on both remaining sides is safe to pair
	source_names = {}
	for src in rest:
		source_names.setdefault(src["account_name"].casefold(), []).append(src)
	target_names = {}
	for acc in target:
		if acc["name"] not in taken:
			target_names.setdefault(acc["account_name"].casefold(), []).append(acc)

	def free_candidates(src):
		return [
			acc
			for acc in target_names.get(src["account_name"].casefold(), [])
			if acc["name"] not in taken and _compatible(src, acc)
		]

	unresolved = []
	for src in rest:
		free = free_candidates(src)
		if len(source_names[src["account_name"].casefold()]) == 1 and len(free) == 1 and take(src, free[0]):
			continue
		unresolved.append(src)

	def mapped_parent(src):
		return matches.get(src["parent_account"]) if src["parent_account"] else None

	# duplicates left: the matched parent must narrow both sides to one
	for src in unresolved:
		parent = mapped_parent(src)
		if not parent:
			continue
		free = [acc for acc in free_candidates(src) if acc["parent_account"] == parent["name"]]
		same = [
			other
			for other in unresolved
			if other["name"] not in matches
			and other["account_name"] == src["account_name"]
			and mapped_parent(other) == parent
		]
		if len(free) == 1 and len(same) == 1:
			take(src, free[0])

	ambiguous = {}
	for src in unresolved:
		if src["name"] in matches:
			continue
		candidates = free_candidates(src)
		if not candidates:
			continue
		parent = mapped_parent(src)
		if parent:
			# protect the branch the identity points at, not every same-name branch
			candidates = [acc for acc in candidates if acc["parent_account"] == parent["name"]] or candidates
		ambiguous[src["name"]] = {acc["name"] for acc in candidates}
	return matches, ambiguous
