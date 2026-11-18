# PharmaSales Insight: interview preparation

Short notes for talking about this project honestly and clearly. All figures come from the
**synthetic** dataset in this repository.

## Your role (say this accurately)

- You **designed the project and directed the work**: you chose the business questions (revenue
  trend, target achievement, regional and product gaps), set the rules (integer paise, a separate
  target table, read-only database access, synthetic data only), and **reviewed every checkpoint**,
  sending back issues to be fixed.
- The **code was written with an AI coding assistant**. Don't say you wrote it independently.
  A fair way to put it: *"I built it with an AI assistant. I specified each step, reviewed the
  output, and learned to explain and check every part of it."*
- The **data is synthetic**. No real pharmaceutical company, product or employee data was used.

## 60-second explanation

> "PharmaSales Insight is a portfolio project that shows the full path from raw data to a
> decision-support dashboard. I used a synthetic dataset of 1,000 pharma sales transactions for
> 2025 across five Indian regions and six fictional products, plus a separate monthly target plan.
> The data goes into SQLite with validation rules, and I answer business questions in SQL, such
> as which region has the lowest achievement and which products missed plan. Then I recompute
> the same results in Pandas and check that every number matches SQL to the paisa. Finally,
> there's a Streamlit dashboard with month, region and product filters, and a recommendations
> panel that suggests what to investigate. For the full year, the data shows ₹81.08 lakh of
> net revenue against an ₹83.60 lakh plan, which is 96.98% achievement. I built it with an AI
> coding assistant. I set the requirements, reviewed each stage, and caught issues like
> double-counted targets and floating-point currency errors."

## Walkthrough of one verified finding

**Finding:** in the full-year view, **Cardiozen 10mg has the largest shortfall** of any region or
product. It earned **₹16,80,352.22** against a plan of **₹18,48,178.61**, a gap of
**₹1,67,826.39** (**90.92%** achievement). It was also below plan in **8 of 12 months**.

**How it was calculated**
1. Add up Cardiozen's sales for each month + region (one actuals row per group).
2. Join those actuals onto Cardiozen's 60 monthly target rows (12 months × 5 regions), keeping
   all of them.
3. Total actual ÷ total plan = 16,80,352.22 ÷ 18,48,178.61 = 90.92%.

**How it was verified:** the same numbers come from the SQL report
(`08_annual_target_misses.sql`), the Pandas reconciliation (`analyze_sales.py`), an independent
SQL query, and what Chrome actually displayed on the dashboard.

**How to talk about it carefully:** *"It's a gap worth investigating. For example, is it fewer
orders or smaller orders, and in which regions? But the plan is flat and the generated sales are
seasonal, so part of the gap is built into the synthetic data. I wouldn't claim a cause from this
dataset."*

## Five likely follow-up questions

**1. Why is the target table separate from the sales table?**
They describe different things. A sales row is one order. A target row is the plan for one
month, region and product. Keeping them apart means a group with **no sales still has a target**.
In this data, 26 of the 360 planned groups had zero transactions, and those show up as 0%
achievement instead of disappearing.

**2. How does the join avoid double-counting?**
I add up the sales to month + region + product **first**, then join from the target table. That
way each target matches one actuals row and is counted once. If you join targets to individual
transactions, a target is repeated once per sale. January / North / Cardiozen has a ₹45,103.83
target and 4 sales, so it would wrongly count as ₹1,80,415.32. I use a `LEFT JOIN` so groups with
no sales stay in, with actual = 0. In Pandas, `validate="one_to_one"` stops the merge if a key is
duplicated.

**3. How are achievement and growth calculated?**
Achievement = **100 × total actual ÷ total plan**, a ratio of totals rather than an average of
percentages, so big targets carry more weight. Growth is this month's actual minus the previous
visible month's actual. For example, February was ₹7,80,737.29 against January's ₹8,90,511.39, a
change of −₹1,09,774.10 (−12.33%). The first month has no growth, and after a ₹0 month the
percentage is shown as unavailable rather than dividing by zero.

**4. Why use integer paise for money?**
Computers store decimals approximately: 0.10 + 0.70 comes out as 0.7999999999999999, which is
less than 0.80, so a group exactly on target could be labelled "below plan". I convert every
amount to whole paise (₹0.10 → 10) before adding or comparing. Integers are exact, so a tie is at
plan and a one-paisa miss is still below plan.

**5. What are the limits of using synthetic data?**
The patterns come partly from how I generated the data: seasonal products, different region
sizes, a randomly drawn rep factor, and a deliberately flat plan. So the dashboard shows that
the **method** works, not real market behaviour. There are no rep or channel targets, it's only
one year and 1,000 transactions, and the recommendations are prompts to investigate, not causal
conclusions. With real data I'd add seasonal targets and check data completeness first.

## Practise out loud

- Explain, in under a minute, why a planned group with zero sales should show 0% instead of
  disappearing, using January / East / Respiclear Inhaler (₹21,659.16 target, no sales).
- Walk through how you'd check that a dashboard number is correct, using the four ways the
  Cardiozen figure was verified.
