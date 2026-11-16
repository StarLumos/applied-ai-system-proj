from rag import Chunk, Retriever, load_chunks, tokenize


def ids(hits):
    return [h.chunk.id for h in hits]


# ---------- loading ----------

def test_load_chunks_reads_every_guide_but_not_the_readme():
    chunks = load_chunks()
    found = {c.id for c in chunks}
    assert len(chunks) >= 12
    assert "README" not in found and "readme" not in found
    assert {"cat_feeding", "dog_feeding", "toxic_foods_and_hazards"} <= found


def test_every_chunk_has_metadata_needed_for_citation():
    for chunk in load_chunks():
        assert chunk.title, chunk.id
        assert chunk.species in {"dog", "cat", "any"}, chunk.id
        assert chunk.source_url.startswith("https://"), chunk.id
        assert chunk.text, chunk.id


def test_frontmatter_is_parsed(tmp_path):
    (tmp_path / "x.md").write_text(
        "---\ntitle: Test Guide\nspecies: Cat\nlife_stage: senior\n"
        "tags: [a, b]\nsource: Src\nsource_url: https://one\nsource_url_2: https://two\n---\n\nBody text.\n",
        encoding="utf-8",
    )
    (chunk,) = load_chunks(tmp_path)
    assert (chunk.title, chunk.species, chunk.life_stage) == ("Test Guide", "cat", "senior")
    assert chunk.tags == ["a", "b"]
    assert chunk.source_urls == ["https://one", "https://two"]
    assert chunk.text == "Body text."


def test_missing_frontmatter_falls_back_to_defaults(tmp_path):
    (tmp_path / "plain_note.md").write_text("Just text.", encoding="utf-8")
    (chunk,) = load_chunks(tmp_path)
    assert chunk.title == "Plain Note"
    assert chunk.species == "any" and chunk.source_url == ""


# ---------- tokenizing ----------

def test_tokenize_drops_stopwords_and_folds_plurals():
    assert tokenize("The dogs walk in the parks") == ["dog", "walk", "park"]
    assert tokenize("grass, vaccines!") == ["grass", "vaccine"]
    assert tokenize("") == []


# ---------- ranking ----------

def test_feeding_queries_match_the_right_species():
    retriever = Retriever()
    assert ids(retriever.retrieve("how often to feed meals", species="cat"))[0] == "cat_feeding"
    assert ids(retriever.retrieve("how often to feed meals", species="dog"))[0] == "dog_feeding"


def test_toxic_food_query():
    hits = Retriever().retrieve("can my dog eat chocolate or grapes")
    assert ids(hits)[0] == "toxic_foods_and_hazards"


def test_results_are_sorted_and_limited_to_k():
    hits = Retriever().retrieve("vaccines vet exam", k=2)
    assert len(hits) == 2
    assert hits[0].score >= hits[1].score


def test_no_match_returns_empty():
    retriever = Retriever()
    assert retriever.retrieve("quantum chromodynamics") == []
    assert retriever.retrieve("") == []
    assert retriever.retrieve("walk", k=0) == []


# ---------- profile filtering ----------

def test_species_filter_excludes_other_species_but_keeps_any():
    hits = Retriever().retrieve("vaccines medication vet", k=20, species="cat")
    species = {h.chunk.species for h in hits}
    assert species <= {"cat", "any"}
    assert "dog_vaccinations_preventive_care" not in ids(hits)
    assert "medication_administration" in ids(hits)


def test_life_stage_filter():
    retriever = Retriever()
    adult = retriever.retrieve("vaccines vet visit", k=20, species="dog", life_stage="adult")
    assert "puppy_care" not in ids(adult) and "senior_pet_care" not in ids(adult)
    puppy = retriever.retrieve("vaccines vet visit", k=20, species="dog", life_stage="puppy")
    assert "puppy_care" in ids(puppy) and "senior_pet_care" not in ids(puppy)


def test_title_and_tags_outweigh_a_passing_body_mention():
    chunks = [
        Chunk(id="a", title="Grooming", text="brushing coat " + "filler " * 5, tags=["grooming"]),
        Chunk(id="b", title="Other", text="grooming " + "filler " * 5, tags=["misc"]),
    ]
    assert ids(Retriever(chunks).retrieve("grooming"))[0] == "a"


def test_empty_corpus_is_safe():
    assert Retriever([]).retrieve("anything") == []


# ---------- pet profile -> query ----------

from datetime import datetime  # noqa: E402

from pawpal_system import Pet, Species, Task  # noqa: E402
from rag import build_query, life_stage_for, retrieve_for_pet  # noqa: E402


def make_pet(age=3, species=Species.DOG, breed="Beagle", name="Rex"):
    return Pet(name=name, age=age, breed=breed, species=species)


def test_life_stage_by_species_and_age():
    assert life_stage_for(make_pet(age=0)) == "puppy"
    assert life_stage_for(make_pet(age=0, species=Species.CAT)) == "kitten"
    assert life_stage_for(make_pet(age=3)) == "adult"
    assert life_stage_for(make_pet(age=6)) == "adult"
    assert life_stage_for(make_pet(age=7)) == "senior"
    assert life_stage_for(make_pet(age=8, species=Species.CAT)) == "adult"
    assert life_stage_for(make_pet(age=9, species=Species.CAT)) == "senior"


def test_life_stage_for_unknown_species():
    assert life_stage_for(make_pet(age=0, species=Species.ANY)) is None
    assert life_stage_for(make_pet(age=3, species=Species.ANY)) == "adult"
    assert life_stage_for(make_pet(age=8, species=Species.ANY)) == "senior"


def test_build_query_includes_profile_but_not_the_age_number():
    query = build_query(make_pet(age=10, breed="Beagle"))
    assert "dog" in query and "Beagle" in query and "senior" in query
    assert "10" not in query


def test_build_query_includes_existing_task_descriptions():
    pet = make_pet()
    pet.add_task(Task("Morning walk", datetime(2026, 1, 1, 8, 0), 30))
    assert "Morning walk" in build_query(pet)


def test_build_query_for_any_species_omits_species_word():
    query = build_query(make_pet(species=Species.ANY, breed=""))
    assert query == "care"


def test_species_any_means_no_species_filter():
    hits = Retriever().retrieve("how often to feed meals", k=20, species="any")
    assert {"cat", "dog"} <= {h.chunk.species for h in hits}


def test_retrieve_for_puppy_returns_puppy_guide_and_no_senior_or_cat_guides():
    found = ids(retrieve_for_pet(make_pet(age=0), k=10))
    assert "puppy_care" in found
    assert "senior_pet_care" not in found
    assert not any(i.startswith("cat_") for i in found)


def test_retrieve_for_senior_cat_returns_senior_guide_and_no_puppy_or_dog_guides():
    found = ids(retrieve_for_pet(make_pet(age=12, species=Species.CAT, breed="Tabby"), k=10))
    assert "senior_pet_care" in found
    assert "puppy_care" not in found
    assert not any(i.startswith("dog_") for i in found)


def test_retrieve_for_adult_dog_excludes_stage_specific_guides():
    found = ids(retrieve_for_pet(make_pet(age=3), k=15))
    assert "puppy_care" not in found and "senior_pet_care" not in found
    assert any(i.startswith("dog_") for i in found)
