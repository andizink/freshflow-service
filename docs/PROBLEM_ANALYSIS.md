# FreshFlow — Problem Analysis (for developers new to the domain)

*This document explains what FreshFlow does, what we are asked to build, and why the task is trickier than it first looks. It assumes no knowledge of grocery retail. Read this before [ARCHITECTURE.md](ARCHITECTURE.md) and the [ADRs](adr/).*

---

## 1. The business problem in plain words

Imagine you run the fruit and vegetable section of a grocery store. Every day you must answer one question, for every single product: **"How many should I order today?"**

Getting this number wrong costs money in both directions:

- **Order too much** → fresh food spoils. A crate of strawberries that doesn't sell by Wednesday goes in the bin. That's pure loss.
- **Order too little** → empty shelves. Customers who came for bananas leave without them (and maybe buy their whole basket at a competitor instead). That's lost revenue and lost trust.

Fresh food makes this uniquely hard because you can't just keep a big safety stock like you can with canned beans — the product dies on the shelf within days.

Three pieces of information feed the decision:

1. **How much do I have right now?** (current inventory)
2. **How much will customers probably buy?** (a demand forecast — FreshFlow computes this; it is *not* part of our task)
3. **When can I even order, and when will it arrive?** (supplier order windows — you can't order everything every day, and delivery takes 1–2 days)

FreshFlow is a company that combines these three inputs and produces, for every store, every day, every item, a single number: the **recommended order quantity**. In our dataset those numbers are already computed. **We do not need to calculate any recommendations ourselves.**

## 2. What we are actually asked to build

A small web service (an API) that does two things:

1. **Load data** — accept four CSV files via HTTP upload and store their contents.
2. **Serve recommendations** — when someone asks *"what should store A order on 2024-03-15?"*, return the list of recommended orders for that store and day.

It must run inside a Docker container, started with nothing more than `docker build` and `docker run`.

That sounds like an afternoon of work. So why is this a serious engineering challenge?

## 3. The real challenge: the data is dirty on purpose

When we profiled the four CSV files (~76,000 rows), we found that they are full of realistic real-world defects — the kind you get when data flows in from store cash registers, supplier systems, and spreadsheets maintained by humans. This is almost certainly intentional: the challenge tests whether we *notice*, and what we *do about it*.

A naive solution that just copies CSV rows into a database would either crash on the bad rows or, worse, silently serve wrong answers. Some examples of what's lurking in the files (the full catalog is in [DATA_GUIDE.md](DATA_GUIDE.md)):

- The same store is spelled eight different ways: `store_a`, `STORE_A`, `" store_a"`, `"store_a "`… If we store these as-is, asking for "store_a" would silently miss thousands of rows.
- Dates appear in two formats in the same column: `2024-01-23` and `23/01/2024`. Treated naively, the second kind either crashes the parser or gets misread as the wrong date.
- Some recommendations say to order **−5 pieces** of something. You cannot order a negative amount of bananas; this row is meaningless as an instruction.
- Some rows reference products (e.g. item `9901`) that don't exist in the product catalog at all. We'd be recommending orders for a mystery item with no name and no price.

## 4. What this means for any solution — the key design tensions

These defects force every solution to take a position on four questions. There is no neutral choice; even "do nothing" is a choice (a bad one).

**Tension 1: Reject, repair, or ignore?**
If we *strictly reject* any file containing an invalid row, nothing would ever load — every file has defects. If we *load everything as-is*, we serve garbage. The middle path — and the one we chose — is: **repair what is unambiguous, set aside what is not, and report everything.** `"STORE_A "` obviously means `store_a`; fixing it loses nothing. But a recommendation of −5 pieces has no obvious correct interpretation, so we don't guess — we set the row aside ("quarantine") and tell the uploader exactly what we excluded and why.

**Tension 2: Where does cleaning happen — on the way in, or on the way out?**
Cleaning at *query time* (every time someone asks for recommendations) means the same messy logic runs on every read, scattered across the codebase, forever. Cleaning at *ingest time* (once, when a file is uploaded) means the database only ever contains trustworthy data and the query code stays simple. We clean at ingest.

**Tension 3: Silent fixes vs. transparency.**
If the service silently fixes and silently drops rows, users can never trust its answers ("why are there only 42 recommendations for this day? Weren't there 45 in the file?"). Our answer: every upload returns a detailed **ingest report** — how many rows arrived, how many were repaired (and how), how many were excluded (and why) — and excluded rows remain retrievable through the API for auditing. Nothing disappears without a paper trail.

**Tension 4: How much data may we destroy?**
Example: inventory says a store has `16.4` pieces of an item, although the README says quantities are whole pieces. Rounding it to 16 at ingest would *destroy information* — the `.4` probably means something (items sold by weight, partial crates). Our rule: store the exact value, flag it in the report, and present a sensibly rounded number in the API response. When in doubt, never throw away information you can't get back.

## 5. Why the seemingly boring requirements also matter

- **"Containerized, `docker build` + `docker run`"** — this quietly rules out solutions needing a separate database server (which would require docker-compose or manual setup). It pushes us toward an embedded database (SQLite). That's [ADR-002](adr/ADR-002-storage.md).
- **"Retrieve recommendations for a given store and day"** — "day" is ambiguous: the day you *place* the order or the day it *arrives*? These differ by 1–2 days in the data. We define it as the **ordering day** (that's the decision the store makes each morning) and return the delivery day in the response. That's the kind of ambiguity you must resolve *explicitly and document*, not leave to chance.
- **"Send us a link to your git repository"** — the reviewers will read the code and history. Clean, well-documented, well-tested code *is* the deliverable, not an optional extra.

## 6. Summary for the impatient

The task is small; the judgment is the product. We are building a two-endpoint FastAPI service whose real substance is a **transparent data-cleansing pipeline**: normalize the unambiguous, quarantine the unfixable, report everything, and prove all of it with tests pinned to the actual defect counts we measured in the files.
