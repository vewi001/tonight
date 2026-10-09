from copy import deepcopy

import pytest

from backend.catalog_merge_policy import plan_field_updates
from backend.catalog_package import CatalogPackageError


def test_unmodified_managed_field_is_corrected():
    plan = plan_field_updates({'overview':'old'}, {'overview':'corrected'}, {'overview':'old'})
    assert plan.changes == {'overview':'corrected'}
    assert plan.baseline == {'overview':'corrected'}


def test_personal_change_is_kept_while_provider_baseline_advances():
    plan = plan_field_updates({'overview':'my text'}, {'overview':'corrected'}, {'overview':'old'})
    assert plan.changes == {}
    assert plan.baseline == {'overview':'corrected'}


def test_legacy_filled_fields_are_not_adopted_or_overwritten():
    plan = plan_field_updates({'title':'legacy','rating':0}, {'title':'new','rating':8}, {})
    assert plan.changes == {} and plan.baseline == {}


def test_legacy_empty_field_can_be_filled_and_later_corrected():
    first = plan_field_updates({'overview':None},{'overview':'first'}, {})
    assert first.changes == {'overview':'first'}
    second = plan_field_updates({'overview':'first'},{'overview':'corrected'},first.baseline)
    assert second.changes == {'overview':'corrected'}


def test_user_cleared_managed_field_remains_empty():
    plan = plan_field_updates({'overview':None},{'overview':'new'},{'overview':'old'})
    assert plan.changes == {} and plan.baseline == {'overview':'new'}


def test_omission_or_null_in_package_never_clears_existing_data():
    plan = plan_field_updates({'overview':'old','director':'name'}, {'overview':None},
                             {'overview':'old','director':'name'})
    assert plan.changes == {}
    assert plan.baseline == {'overview':'old','director':'name'}


def test_identifiers_are_never_part_of_field_patch():
    plan = plan_field_updates({'id':'local','tmdb_id':10,'overview':'old'},
                             {'id':'remote','tmdb_id':10,'overview':'new'},
                             {'id':'local','tmdb_id':10,'overview':'old'})
    assert plan.changes == {'overview':'new'}
    assert plan.baseline == {'overview':'new'}


def test_unknown_incoming_field_is_rejected_without_mutation():
    current = {'title':'keep','private_note':'secret'}
    before = deepcopy(current)
    with pytest.raises(CatalogPackageError):
        plan_field_updates(current,{'private_note':'changed'}, {})
    assert current == before


def test_repeat_is_noop_and_private_fields_do_not_enter_patch():
    plan = plan_field_updates({'overview':'same','private_note':'secret'},
                             {'overview':'same'}, {'overview':'same','private_note':'secret'})
    assert plan.changes == {} and plan.baseline == {'overview':'same'}


def test_lists_are_compared_as_json_and_outputs_do_not_alias_inputs():
    current = {'genres':['драма']}
    incoming = {'genres':['комедия']}
    baseline = {'genres':['драма']}
    original = deepcopy((current,incoming,baseline))
    plan = plan_field_updates(current,incoming,baseline)
    assert plan.changes == {'genres':['комедия']}
    plan.changes['genres'].append('test')
    plan.baseline['genres'].append('test')
    assert (current,incoming,baseline) == original


def test_empty_string_is_preserved_as_a_personal_edit_not_treated_as_missing():
    plan = plan_field_updates({'overview':''},{'overview':'new'},{'overview':'old'})
    assert plan.changes == {}
