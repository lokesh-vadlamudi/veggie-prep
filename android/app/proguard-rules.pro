-keep class com.google.ai.edge.litertlm.** { *; }
-dontwarn com.google.ai.edge.litertlm.**

# These two models are persisted as Gson JSON in the on-device SQLite database.
# Their field names must stay stable across app upgrades.
-keep class com.lokeshvadlamudi.veggieprep.data.MealIngredient { *; }
-keep class com.lokeshvadlamudi.veggieprep.data.MealAllocation { *; }
