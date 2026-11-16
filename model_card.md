## 1. Limitations and biases

- **A small, US-centered knowledge base.** There are 12 guides, only for dogs and cats, drawn mostly from US sources (VCA, ASPCA, AVMA, FDA, AKC, Cornell). It reflects US norms, such as the poison hotline number and US rabies-law assumptions. It has nothing for rabbits, birds, reptiles or other animals.
- **Source bias.** The guides come from veterinary-chain, nonprofit and government pages, not clinical studies. Where sources disagreed (for example whether leptospirosis is core for dogs), I followed the source I could read, not a consensus. AAHA's site blocked automated reads, so its guidelines aren't used.
- **Crude life stages.** The "senior" ages are fixed at 7 for dogs and 9 for cats, because the pet has no size field. VCA says large dogs are senior at 6-7 and giant dogs at 4-5, so big dogs get adult advice too late. Age is whole years, so a 10-month-old is a "puppy" and an 11-month-old is too.
- **Breed is ignored.** The retriever doesn't use it, so a Chihuahua and a Great Dane get the same tasks.
- **The task defaults are mine.** Durations, priorities and frequencies in the "Suggested tasks" lists are my own defaults, not claims from the sources. The scheduler can't repeat monthly tasks, so "nail trim every 3-4 weeks" is a one-off.
- **Canned reasons and no health context.** Suggestions don't account for a pet's conditions or medications, and the explanation text is generic.
- **Weak keyword search.** It can't connect different wording ("shots" and "vaccines"). I also tuned the stopword list after seeing a failure, and I wrote the evaluation myself, so its 95% and 100% scores are optimistic.

## 2. Could it be misused, and how would I prevent that?

- **Treating it as veterinary advice (the main risk).** An owner might delay a vet visit or skip real care. The screen says the suggestions are general information, each shows its source link, and the medication guide gives no doses. What isn't built: the app doesn't detect an emergency such as "my dog ate chocolate" and tell the owner to call a vet immediately. I'd add that as the next safeguard.
- **A tampered knowledge base.** Someone could edit a guide so wrong advice appears next to a trustworthy-looking link. The guides are in version control, so a change is visible in review, and tests check that every guide loads with its citation. I haven't added a checksum or sign-off step.
- **Smaller risks.** With no language model, there's no prompt injection and no invented advice. Nothing the user types leaves the machine, pet and task names are kept out of the logs, and nothing is stored between sessions. Removing the language-model step was partly a safety choice.

## 3. What surprised me while testing reliability

- **A perfect score made me suspicious.** My first evaluation was 100%. When I added paraphrased questions, "my dog swallowed a raisin" failed, because filler words like "my" and "should" outweighed the one meaningful word.
- **Tasks silently vanished in the real page.** Streamlit's selectboxes returned copies of pets, so tasks I added went to a copy. Unit tests passed while the page did nothing. This also broke parts of the original app, such as the pet filter and "Mark complete".
- **A link was wrong without any test failing.** A `---` inside a URL truncated a source link. I found it only by reading real sample output.
- **My own drafts were wrong.** When I checked my first guides against their sources, I'd misquoted things such as kitten meal counts and cat play durations.

## 4. Collaboration with AI

I worked with Claude throughout the project.

**A suggestion I accepted: per-topic retrieval.** Claude pointed out that one generic search ("dog care") ranked guides arbitrarily for adult pets. It proposed running one search per care topic (feeding, exercise, vet care, grooming, medication) and merging the results. I accepted it, and then added a safety topic myself. Each pet now gets one relevant guide per topic.

**A suggestion I did not accept as written: the Claude-generated suggestions.** Claude's plan was to send the retrieved guides to a model, which would write the task suggestions as JSON. It built that, but I asked whether the project could work without a key, and then had the model step removed entirely. I didn't want the app to depend on an API key, and the generation step had only been tested against a stub, never the real API. Retrieval plus curated task lists could be tested completely.

Claude also built breed-specific filtering and a Golden Retriever guide. I asked whether that guide was necessary, the answer was no, and I had the filter removed. It was extra machinery for one breed, and its sources were the weakest in the project.
