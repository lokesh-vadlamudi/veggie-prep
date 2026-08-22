# Veggie Prep Privacy Policy

Effective: August 22, 2026

Veggie Prep is published by Vadlamudi Labs. This policy explains how the
native Android app handles information.

## Summary

Veggie Prep does not require an account. Vadlamudi Labs does not collect or
receive pantry items, meal history, imported model files, AI credentials,
analytics, advertising identifiers, or diagnostic telemetry from the app.

Pantry items, inventory history, meal suggestions, imported models, and AI
settings are stored in the app's private storage on the device. Android cloud
backup is disabled.

## Receipt scanning

When the user scans a receipt or chooses a receipt photo, Android and Google ML
Kit process the image on the device to recognize text. Veggie Prep does not
retain the original receipt image. Before an import, the user reviews and can
edit or exclude every recognized grocery. Only approved pantry details,
sanitized grocery-line labels, the merchant label, and purchase date are stored
in private app storage; totals, payment-card details, and unrelated receipt
metadata are not saved.

Google Play services may collect limited operational metrics and diagnostics
for the document-scanning and text-recognition APIs under Google's terms.
Vadlamudi Labs does not receive that information and does not add its own
analytics or advertising tracking.

## Meal generation

When an on-device model is selected, meal generation remains on the device.

When the user selects an OpenAI-compatible network API, Veggie Prep displays
the destination and a preview before sending data. The request can contain:

- pantry item names;
- quantities and units;
- expiry dates; and
- the requested servings, time limit, and meal preference.

A weekly plan creates five meal requests. Before each request, the app removes
quantities already reserved by earlier meals and sends the updated remaining
pantry preview.

Storage locations, purchase dates, and inventory history are not included in
the meal prompt. If the configured service requires an API key, the key is
stored using Android Keystore encryption and sent only as an authorization
header to the endpoint chosen by the user.

Network providers are selected and configured by the user. Information sent
to those providers is processed under their respective terms and privacy
policies. Vadlamudi Labs does not operate or receive data from those services.

## Permissions and imported files

The Internet permission is used only when a network AI provider is configured.
The system document picker is used when the user chooses a receipt photo or
imports a compatible on-device model. The Google Play services document
scanner provides the camera-based receipt flow without giving Veggie Prep
broad camera access. Imported models are copied into private app storage.

## Retention and deletion

Local information remains on the device until the user changes or removes it.
Clearing Veggie Prep's app storage or uninstalling the app removes its local
data. A network provider may retain requests according to its own policy.

## Children

Veggie Prep is a general household utility and is not directed to children
under 13.

## Changes and contact

Material changes will be reflected in this policy and, when appropriate, in
the app. For privacy questions, use the developer contact information shown on
Veggie Prep's Google Play listing.
