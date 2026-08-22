# Veggie Prep Play Store listing

## App name

Veggie Prep

## Short description

Track pantry items locally and turn what you have into practical meal ideas.

## Full description

Veggie Prep helps you keep track of vegetables, groceries, and pantry staples
without creating an account. Add what you have, record what was used or
discarded, and see which ingredients should be used soon.

Quickly find more than 450 household foods—from eggs, sourdough, roti, pasta,
produce, sauces, frozen foods, and leftovers to Indian ingredients with names
such as palak, methi, keerai, and kothimeera. The built-in catalog works
offline and prefills practical storage, quantity, and shelf-life suggestions
that you can edit before or after saving.

Turn your current pantry into a meal suggestion with your choice of AI:

- Use Gemini Nano on supported Android devices.
- Import a compatible on-device model.
- Connect an OpenAI-compatible service that you control.

Privacy is built into the workflow. Pantry and meal history stay in private
storage on your phone. On-device generation keeps the entire request local. If
you choose a network service, Veggie Prep shows the destination and exact
pantry preview before sending anything. Storage locations, purchase dates, and
inventory history are never included in the meal prompt.

Key features:

- Local-first pantry inventory
- On-device receipt scan or photo import with review before saving
- Offline catalog of 450+ household foods and regional aliases
- Editable expiry dates for existing pantry items
- Dedicated Snacks section for available snacks
- Expiry-first meal planning that skips expired ingredients
- Configurable multi-day breakfast, lunch, and dinner planning in one AI request
- Pantry quantity checks and missing-ingredient shopping list
- Confirmed Cook & deduct pantry updates
- Use and discard history
- Saved meal suggestions
- On-device and user-configured AI options
- Encrypted API-key storage
- No account, ads, analytics, or cloud backup

Veggie Prep is designed to make everyday meal planning simpler while keeping
you in control of where your data goes.

## Release notes — 0.3.0

Scan a grocery receipt or choose a photo, review every recognized item, and add
the selected groceries to your pantry in one step. Estimated quantities and
expiry dates are clearly labeled, uncertain matches stay unchecked, duplicate
imports are blocked, and a completed import can be undone. You can also create
a five-meal plan for next week that prioritizes expiring ingredients and
reserves pantry quantities across the whole plan.

## Previous release — 0.2.0

Quick Add now covers 450+ household foods, including breads, flatbreads, eggs,
proteins, prepared foods, sauces, frozen items, beverages, and leftovers.
Pantry expiry dates can now be changed or cleared after an item is added.

## Suggested category

Food & Drink

## Data-safety working notes

- No developer collection or sharing.
- No account creation.
- No advertising or analytics SDKs.
- User-initiated network AI requests go only to the endpoint configured by the
  user after a destination and data preview.
- Receipt images are processed on-device; the original photo is not retained by
  Veggie Prep. Recheck Google Play's Data safety answers for the limited ML Kit
  operational metrics and diagnostics before releasing 0.3.0.
- Pantry and meal data remain in app-private storage; Android backup is off.
