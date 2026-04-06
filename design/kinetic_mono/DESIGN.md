# Design System Strategy: Functional Brutalism

## 1. Overview & Creative North Star
The Creative North Star for this design system is **"The Kinetic Ledger."** 

In an industry saturated with soft gradients and motivational imagery, this system takes an uncompromising, editorial approach to fitness. It treats human performance as raw data. By stripping away all aesthetic "noise"—shadows, rounded corners, and decorative flourishes—we elevate the user’s metrics to the level of high-performance instrumentation. 

The design breaks the "template" look through **Extreme Typographic Scale** and **Intentional Asymmetry**. We do not center-align for comfort; we left-align for speed and urgency. The layout should feel like a digital terminal—precise, cold, and immensely powerful.

## 2. Colors: High-Voltage Contrast
This system operates on a binary logic. If it isn't data, it’s background.

### The Palette
*   **Background (#131313):** Our "Absolute Zero." All energy originates here.
*   **Primary (#FFFFFF):** Used for pure information. White is the signal.
*   **Accent / Tertiary (#72FF70):** Our "Matrix Green." This is reserved strictly for kinetic energy: active timers, "Start Workout" buttons, and PR (Personal Record) indicators.
*   **Surface Tiers:** We use `surface-container-low` (#1B1B1B) and `surface-container-high` (#2A2A2A) to block out data groups.

### The "No-Line" Rule
Traditional 1px borders are forbidden. They create visual clutter that slows down data ingestion. Boundaries must be defined solely through background shifts. To separate a workout set from a rest period, shift the container from `surface` to `surface-container-low`.

### Surface Hierarchy & Nesting
Treat the UI as a monolithic block that has been "carved out." 
*   **Level 0:** `surface` (#131313) - The base of the app.
*   **Level 1:** `surface-container-low` (#1B1B1B) - Primary data cards (e.g., a Workout Card).
*   **Level 2:** `surface-container-highest` (#353535) - Internal nested elements (e.g., an individual set within a workout).

### The "Ghost Border" Fallback
If accessibility requires a container definition against a similar background, use the `outline-variant` (#474747) at **10% opacity**. It should be felt, not seen.

## 3. Typography: The Metric-First Hierarchy
Typography is our primary tool for "Functional Brutalism." We utilize two high-contrast typefaces: **Space Grotesk** for data/headers (technical, geometric) and **Inter** for UI instructions (neutral, readable).

*   **Display-LG (Space Grotesk, 3.5rem):** Reserved for the "Hero Metric." Your heart rate, your current weight, or the countdown timer. It should feel massive, almost uncomfortably large.
*   **Headline-LG (Space Grotesk, 2rem):** Section headers. Upper-case is encouraged to reinforce the brutalist tone.
*   **Body-MD (Inter, 0.875rem):** All secondary instructional text. 
*   **Label-SM (Space Grotesk, 0.6875rem):** Micro-data labels (e.g., "BPM", "KCAL", "KG"). Always paired with high-scale display numbers.

## 4. Elevation & Depth: Tonal Layering
We reject the concept of the "Z-axis" through shadows. Depth is achieved through **Luminance Stacking.**

*   **The Layering Principle:** To "elevate" a floating action button or a modal, we do not cast a shadow. Instead, we place the element on a `surface-bright` (#393939) container. The eye perceives the increase in brightness as a decrease in physical distance.
*   **Glassmorphism (The "HUD" Effect):** For persistent overlays (like a music controller during a workout), use a `surface` color with 70% opacity and a `20px backdrop-blur`. This maintains the "Brutalist" edge while ensuring the data beneath remains a ghosted reference.

## 5. Components: Precision Primitives

### Buttons
*   **Primary (Action):** Background: `#72FF70`, Text: `#002203` (Heavy weight). Sharp 0px corners.
*   **Secondary (Navigation):** Background: `#FFFFFF`, Text: `#131313`.
*   **Tertiary (Utility):** Outline-variant at 20% opacity. Text: `#FFFFFF`.

### Input Fields
*   **State:** No boxes. Use a `surface-container-highest` bottom-bar (2px) only. 
*   **Active:** The bottom bar shifts to the accent color (`#72FF70`). Text input should use `display-sm` for weight/reps entry.

### Cards & Lists
*   **The Divider Ban:** Dividers are replaced by 24px or 32px of vertical "Dead Space." 
*   **Groupings:** Use `surface-container-low` for the card body. On tap/press, shift the background immediately to `surface-container-highest`. No transition animations longer than 100ms.

### New Component: The "Metric Strip"
A full-bleed horizontal bar using `tertiary-container` (#00A827) that grows or shrinks based on workout progress. It acts as a progress bar but spans the entire width of the screen, acting as a structural element.

## 6. Do's and Don'ts

### Do
*   **DO** use extreme scale. If a number is important, make it 4x larger than the label.
*   **DO** embrace 0px corners. Only use 4px if the component feels physically "sharp" enough to cause friction.
*   **DO** use monospaced alignment for numbers to prevent "jitter" during active timers.

### Don't
*   **DON'T** use icons for everything. A brutalist system prefers the word "SAVE" over a floppy disk icon.
*   **DON'T** use 1px borders to separate content. Use the Spacing Scale.
*   **DON'T** use "Success Green" and "Error Red" in their traditional sense. Red should only be used for `error` (#FFB4AB) in critical system failures; progress is always our primary accent color.