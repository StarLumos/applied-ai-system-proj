# PawPal+ with RAG: care suggestions grounded in sourced guides

This project extends the original **PawPal+ (without RAG)**, which is described next.

## Original project: PawPal+ (without RAG)

PawPal+ was a Streamlit scheduling assistant for busy pet owners. Its goal was to let an owner track care tasks (walks, feeding, medication, grooming) for one or more pets and turn them into a daily plan that respects priority and the owner's available hours. It could sort and filter tasks, detect overlapping tasks across pets, repeat daily and weekly tasks automatically, and was covered by 26 automated tests. Its full documentation is in [docs/original_pawpal.md](docs/original_pawpal.md).

## Current project: PawPal+ with RAG

**What it does.** The original scheduler still works, and the app now also answers a question the owner usually has first: *what care does my pet actually need?* You add a pet with its species and age, and PawPal+ **retrieves** the matching pages from a knowledge base of 12 care guides (feeding, exercise, vaccines, grooming, medication and safety for dogs and cats, plus puppy and senior care). It turns those guides' task lists into suggestions, each showing its **source link**. You review them, adjust the start time, and add the ones you want to your schedule, where the original conflict checking applies.

**Why it matters.** New pet owners often don't know what a puppy or a 12-year-old cat needs, and generic advice online is hard to trust. Here every suggestion traces back to a named source, the guides were checked against those sources by hand, and nothing reaches the schedule until the owner clicks Add.

## Architecture overview

![PawPal+ system diagram](diagrams/system_diagram.png)

The diagram ([Mermaid source](diagrams/system_diagram.mmd)) is a class diagram of the whole system. Reading it by stage:

- **Input:** the owner enters a pet (species, age, breed) in the Streamlit app, and the 12 guides sit in `knowledge/`, each with a source URL.
- **Process:** `rag.py` turns the pet into a life stage (puppy, adult, senior) and runs one query per care topic. The `Retriever` ranks guides with BM25 and drops any that don't fit the pet's species or life stage. `suggestions.py` reads each retrieved guide's "Suggested tasks" list into cited `Suggestion` objects, and the original `Scheduler` sorts tasks and finds conflicts.
- **Output:** suggestion cards with sources, and a daily schedule with conflict warnings.
- **Where people and tests check the results:** the owner reviews every suggestion and its source before clicking Add and decides what to do about conflicts. A person checked each guide against its source pages. The `pytest` suite and a retrieval evaluation (`eval_retrieval.py`) check the code and the retrieval quality, and `logs/pawpal.log` records what the system did.

## Setup

**Requirements:** Python 3.9 or newer (developed and tested on 3.13). No API key, account or internet connection is needed once the packages are installed.

Run these from the project folder, the one that contains `app.py`.

1. **Create a virtual environment:**

   ```bash
   python -m venv .venv
   ```

2. **Activate it.** Your prompt should start with `(.venv)` afterward.

   | Shell | Command |
   |-------|---------|
   | Windows PowerShell | `.venv\Scripts\Activate.ps1` |
   | Windows Command Prompt | `.venv\Scripts\activate.bat` |
   | macOS / Linux | `source .venv/bin/activate` |

   If PowerShell says scripts are disabled, run `Set-ExecutionPolicy -Scope Process RemoteSigned` once in that window and try again.

3. **Install the dependencies** (Streamlit and pytest):

   ```bash
   pip install -r requirements.txt
   ```

4. **Check that it works.** All tests should pass:

   ```bash
   python -m pytest -q
   ```

5. **Run it** (activate the environment first in any new terminal):

   | What | Command |
   |------|---------|
   | Web app (opens at <http://localhost:8501>) | `streamlit run app.py` |
   | Command-line demo of the scheduler | `python main.py` |
   | Retrieval evaluation report | `python eval_retrieval.py` |

   In the app: add a pet and choose its **species**, click **Suggest care tasks**, click **Add to schedule** on the tasks you want, then **Generate schedule**. Click Generate again after adding more tasks.

**If something goes wrong:** `streamlit` not recognized means the environment isn't active (or use `python -m streamlit run app.py`). `ModuleNotFoundError` means you're not in the project folder. Port in use: add `--server.port 8502`. Details of any error are in `logs/pawpal.log`; set `PAWPAL_LOG_LEVEL=DEBUG` for more.

## Sample interactions

These are real outputs from the running system. There is no language model, so the same input always gives the same output.

**1. An adult dog**

```
Input:   species=dog, age=3, breed="Golden Retriever", no tasks yet   (life stage: adult)
Output:  10 suggestions, the first six shown:
  Breakfast feeding                  10 min  HIGH    daily   <- Dog Feeding Frequency
  Dinner feeding                     10 min  HIGH    daily   <- Dog Feeding Frequency
  Morning walk                       30 min  HIGH    daily   <- Dog Exercise Needs
  Evening walk                       20 min  MEDIUM  daily   <- Dog Exercise Needs
  Play or training session           15 min  LOW     daily   <- Dog Exercise Needs
  Vaccination booster appointment    45 min  HIGH    none    <- Dog Vaccinations and Preventive Care
```

**2. A puppy: the same dog at age 0 gets extra, stage-specific tasks**

```
Input:   species=dog, age=0, breed="Labrador"   (life stage: puppy)
Output:  13 suggestions: the 10 above, plus
  Puppy meals                        10 min  HIGH    daily   <- Puppy Care Basics
  Short play or training session     10 min  MEDIUM  daily   <- Puppy Care Basics
  Vet vaccination visit              45 min  HIGH    none    <- Puppy Care Basics
  (no "Senior wellness exam", no cat tasks)
```

**3. A senior cat: species and age change everything**

```
Input:   species=cat, age=12, breed="Tabby"   (life stage: senior)
Output:  14 suggestions, including
  Senior wellness exam               60 min  HIGH    none    <- Senior Pet Care
  Scoop litter box                    5 min  HIGH    daily   <- Cat Litter Box and Grooming
  Flea preventive                     5 min  HIGH    none    <- Cat Vaccinations and Preventive Care
  (no "Kitten vaccination visit", no dog tasks)
Source:  https://vcahospitals.com/resources/senior/when-is-your-pet-considered-a-senior
```

**4. Searching the guides with a question**

```
Input:   "can my dog eat chocolate or grapes"
Output:  1. toxic_foods_and_hazards   (score 8.57)
            https://www.aspca.org/pet-care/aspca-poison-control/people-foods-avoid-feeding-your-pets
         2. dog_feeding              (score 2.06)
         3. puppy_care               (score 1.38)
```

**5. A conflict is warned about, not blocked.** An owner with a vet check-up at 08:00 adds "Breakfast feeding" at 08:15:

```
Output:  Heads up: 'Breakfast feeding' (Buddy, 08:15-08:25) overlaps
         'Vet check-up' (Buddy, 08:00-09:00) (same pet)
         (the task is still added; the owner decides what to do)
```

## Design decisions

- **Retrieval plus curated task lists, not an LLM writing the advice.** It needs no key, gives identical results every time, and every suggestion traces to a source. The trade-off: suggestions are generic, with a canned reason, and aren't tailored to the pet's situation.
- **Plain BM25 keyword search, no embeddings.** It is simple and easy to test offline. The trade-off: it can't connect different wording ("shots" and "vaccines").
- **12 hand-checked guides for dogs and cats only.** The content is trustworthy, but it's small and covers no other animals.
- **The owner stays in control.** Suggestions are proposals, and conflicts warn but never block. The trade-off is a few more clicks.

## Testing summary

- **What worked:** 130 tests pass (the 26 original plus 104 new), including tests that drive the real page.
- **What didn't, at first:**
  - Filler words like "my" and "should" outranked the one meaningful word in a question.
  - Selectboxes handed back copies of pets, so added tasks silently vanished. Only tests that drove the real page found it.
  - My first drafts of the guides contained claims their sources didn't support.
- **Still weak:** "when does my kitten need its shots" ranks the play guide first and the vaccine guide second. The evaluation is also small and I wrote it myself, so its scores are optimistic.
- **What I learned:** the bugs that mattered showed up in realistic end-to-end use, not in the neat unit tests.

## Reflection

This project taught me that an AI assistant can produce something that looks finished long before it is correct: my first guide drafts read well but misquoted their sources, and only reading the actual pages caught it. It also taught me to test the real thing, not a stand-in. Mocks and unit tests passed while the real page was losing tasks. Finally, I learned that removing a feature can be the better engineering. A language-model step I couldn't verify live was worse than a simpler, traceable one I could test completely.

## More documentation

- [Original PawPal+ (without RAG)](docs/original_pawpal.md): scheduler design, features and demo
- [Knowledge base notes](knowledge/README.md): guide format and how each was verified
- Diagrams: [system diagram](diagrams/system_diagram.mmd), [original UML](diagrams/uml_final.mmd)
- [reflection.md](reflection.md) and [ai_interactions.md](ai_interactions.md): project reflections
