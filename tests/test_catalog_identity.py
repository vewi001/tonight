from copy import deepcopy

import pytest

from backend.catalog_identity import resolve_catalog_ids
from backend.catalog_package import CatalogPackageError


def movie(identifier,tmdb=None,title='Film',year=2020,original=None):
    return {'id':identifier,'tmdb_id':tmdb,'title':title,'year':year,'original_title':original}


def test_tmdb_match_keeps_local_id_despite_changed_title_and_year():
    assert resolve_catalog_ids([movie('local',10)], [movie('remote',10,'Corrected',2021)]) == {'remote':'local'}


def test_same_id_and_same_tmdb_keeps_user_edited_identity_fields():
    assert resolve_catalog_ids([movie('local',10,'My title',2022)], [movie('local',10)]) == {'local':'local'}


def test_starter_match_uses_original_title_and_year():
    current = movie('starter',None,'Личный перевод',original=' Original ')
    incoming = movie('tmdb-10',10,'Другой перевод',original='original')
    assert resolve_catalog_ids([current],[incoming]) == {'tmdb-10':'starter'}


def test_whitespace_original_title_falls_back_to_title():
    assert resolve_catalog_ids([movie('local',original='   ')],[movie('remote')]) == {'remote':'local'}


def test_whitespace_original_titles_do_not_merge_different_movies():
    assert resolve_catalog_ids([movie('local',title='First',original=' ')],
                               [movie('remote',title='Second',original='\t')]) == {'remote':'remote'}


@pytest.mark.parametrize('incoming', [movie('local',11),movie('local',None,'Other'),movie('local',None,year=2021)])
def test_conflicting_local_id_is_rejected(incoming):
    with pytest.raises(CatalogPackageError):
        resolve_catalog_ids([movie('local',10)],[incoming])


def test_strong_match_cannot_overwrite_id_belonging_to_another_movie():
    with pytest.raises(CatalogPackageError):
        resolve_catalog_ids([movie('canonical',10),movie('occupied',20)], [movie('occupied',10)])


def test_distinct_tmdb_movies_with_same_title_and_year_are_not_merged():
    assert resolve_catalog_ids([movie('local',10)],[movie('remote',20)]) == {'remote':'remote'}


def test_new_movie_retains_incoming_id():
    assert resolve_catalog_ids([], [movie('new',10)]) == {'new':'new'}


def test_ambiguous_weak_identity_is_rejected():
    with pytest.raises(CatalogPackageError):
        resolve_catalog_ids([movie('one'),movie('two')],[movie('incoming')])


def test_two_rows_cannot_claim_one_existing_movie():
    with pytest.raises(CatalogPackageError):
        resolve_catalog_ids([movie('local',10)],[movie('one',10),movie('two',10)])


def test_new_weak_aliases_are_rejected_before_any_write():
    with pytest.raises(CatalogPackageError):
        resolve_catalog_ids([], [movie('one'),movie('two')])


def test_new_strong_distinct_movies_with_same_name_are_allowed():
    assert resolve_catalog_ids([], [movie('one',10),movie('two',20)]) == {'one':'one','two':'two'}


def test_case_only_alias_preserves_actual_local_id_and_inputs():
    current, incoming = [movie('Film',10)], [movie('film',10)]
    before = deepcopy((current,incoming))
    assert resolve_catalog_ids(current,incoming) == {'film':'Film'}
    assert (current,incoming)==before


def test_duplicate_local_strong_identity_is_rejected():
    with pytest.raises(CatalogPackageError):
        resolve_catalog_ids([movie('one',10),movie('two',10)],[])
