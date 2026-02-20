# Microsoft Pragmatic Rust Guidelines — Detailed Reference

Source: https://microsoft.github.io/rust-guidelines/

Use this file when you need detailed guidance on any M-prefixed checklist item.
Each section includes the rationale, requirements, and code examples.

## Table of Contents

- [Universal](#universal)
  - [M-UPSTREAM-GUIDELINES](#m-upstream-guidelines)
  - [M-STATIC-VERIFICATION](#m-static-verification)
  - [M-LINT-OVERRIDE-EXPECT](#m-lint-override-expect)
  - [M-PUBLIC-DEBUG](#m-public-debug)
  - [M-PUBLIC-DISPLAY](#m-public-display)
  - [M-SMALLER-CRATES](#m-smaller-crates)
  - [M-CONCISE-NAMES](#m-concise-names)
  - [M-REGULAR-FN](#m-regular-fn)
  - [M-PANIC-IS-STOP](#m-panic-is-stop)
  - [M-PANIC-ON-BUG](#m-panic-on-bug)
  - [M-DOCUMENTED-MAGIC](#m-documented-magic)
  - [M-LOG-STRUCTURED](#m-log-structured)
- [Library / Interoperability](#library--interoperability)
  - [M-TYPES-SEND](#m-types-send)
  - [M-ESCAPE-HATCHES](#m-escape-hatches)
  - [M-DONT-LEAK-TYPES](#m-dont-leak-types)
- [Library / UX](#library--ux)
  - [M-SIMPLE-ABSTRACTIONS](#m-simple-abstractions)
  - [M-AVOID-WRAPPERS](#m-avoid-wrappers)
  - [M-DI-HIERARCHY](#m-di-hierarchy)
  - [M-ERRORS-CANONICAL-STRUCTS](#m-errors-canonical-structs)
  - [M-INIT-BUILDER](#m-init-builder)
  - [M-INIT-CASCADED](#m-init-cascaded)
  - [M-SERVICES-CLONE](#m-services-clone)
  - [M-IMPL-ASREF](#m-impl-asref)
  - [M-IMPL-RANGEBOUNDS](#m-impl-rangebounds)
  - [M-IMPL-IO](#m-impl-io)
  - [M-ESSENTIAL-FN-INHERENT](#m-essential-fn-inherent)
- [Library / Resilience](#library--resilience)
  - [M-MOCKABLE-SYSCALLS](#m-mockable-syscalls)
  - [M-TEST-UTIL](#m-test-util)
  - [M-STRONG-TYPES](#m-strong-types)
  - [M-NO-GLOB-REEXPORTS](#m-no-glob-reexports)
  - [M-AVOID-STATICS](#m-avoid-statics)
- [Library / Building](#library--building)
  - [M-OOBE](#m-oobe)
  - [M-SYS-CRATES](#m-sys-crates)
  - [M-FEATURES-ADDITIVE](#m-features-additive)
- [Applications](#applications)
  - [M-MIMALLOC-APP](#m-mimalloc-app)
  - [M-APP-ERROR](#m-app-error)
- [FFI](#ffi)
  - [M-ISOLATE-DLL-STATE](#m-isolate-dll-state)
- [Safety](#safety)
  - [M-UNSAFE](#m-unsafe)
  - [M-UNSAFE-IMPLIES-UB](#m-unsafe-implies-ub)
  - [M-UNSOUND](#m-unsound)
- [Performance](#performance)
  - [M-THROUGHPUT](#m-throughput)
  - [M-HOTPATH](#m-hotpath)
  - [M-YIELD-POINTS](#m-yield-points)
- [Documentation](#documentation)
  - [M-FIRST-DOC-SENTENCE](#m-first-doc-sentence)
  - [M-MODULE-DOCS](#m-module-docs)
  - [M-CANONICAL-DOCS](#m-canonical-docs)
  - [M-DOC-INLINE](#m-doc-inline)
- [AI](#ai)
  - [M-DESIGN-FOR-AI](#m-design-for-ai)

---

## Universal

### M-UPSTREAM-GUIDELINES
**Follow the Upstream Guidelines**

Avoid repeating community-learned mistakes and prevent surprising users/contributors.

Key references to follow:
- Rust API Guidelines (the C-prefixed items in the companion checklist)
- Rust Style Guide
- Rust Design Patterns
- Rust Reference — Undefined Behavior

Frequently overlooked items from the API Guidelines:
- C-CONV: Conversions follow `as_`, `to_`, `into_` naming
- C-GETTER: Getter names follow Rust convention (no `get_` prefix)
- C-COMMON-TRAITS: Types implement Copy, Clone, Eq, PartialEq, Ord, PartialOrd, Hash, Default, Debug
- C-CTOR: Constructors are static inherent methods
- C-FEATURE: Feature names avoid placeholder words

### M-STATIC-VERIFICATION
**Use Static Verification**

Enable these compiler lints:
```
ambiguous_negative_literals, missing_debug_implementations,
redundant_imports, redundant_lifetimes, trivial_numeric_casts,
unsafe_op_in_unsafe_fn, unused_lifetimes
```

Recommended tools: clippy (cargo, complexity, correctness, pedantic, perf, style, suspicious categories), rustfmt, cargo-audit, cargo-hack, cargo-udeps, miri.

### M-LINT-OVERRIDE-EXPECT
**Lint Overrides Use `#[expect]`**

Use `#[expect]` instead of `#[allow]` so you get warnings when the suppressed lint is no longer triggered (meaning the override is stale). Include a `reason` attribute for context.

### M-PUBLIC-DEBUG
**Public Types are Debug**

All public types must implement `Debug`. Use `#[derive(Debug)]` for regular types. Custom implementations required for sensitive data must include unit tests verifying no sensitive information leaks.

### M-PUBLIC-DISPLAY
**Public Types Meant to be Read are Display**

Types expected to be read by consumers (especially error types and string-like wrappers) should implement `Display`. Handle sensitive data per M-PUBLIC-DEBUG guidance.

### M-SMALLER-CRATES
**If in Doubt, Split the Crate**

Favor more crates over fewer to improve compile times and modularity. Extract independently-usable submodules into separate crates. Re-export functionality when joining crates. Rule of thumb: "crates for items used alone; features unlock extra functionality."

### M-CONCISE-NAMES
**Names are Free of Weasel Words**

Avoid meaningless terms like "Service", "Manager", "Factory". Names should convey specific purpose. Use `Bookings` instead of `BookingService`; `BookingDispatcher` for submission operations. Factories should be called `Builder`.

### M-REGULAR-FN
**Prefer Regular over Associated Functions**

Associate functions primarily with instance creation. General-purpose computation unrelated to a receiver belongs as regular functions, not in `impl` blocks. Reduces unnecessary noise on the caller side.

### M-PANIC-IS-STOP
**Panic Means "Stop the Program"**

Panics signal immediate program termination. Valid reasons: programming errors (e.g., `expect`), const contexts, user-requested operations, poison detection. Never use panics for error communication or recoverable conditions.

### M-PANIC-ON-BUG
**Detected Programming Bugs are Panics, Not Errors**

Unrecoverable programming errors (contract violations, invariant breaks) must panic — don't return `Error` types. APIs need not detect violations if checks are impossible or expensive.

### M-DOCUMENTED-MAGIC
**All Magic Values and Behaviors are Documented**

Hardcoded values require comments explaining: why chosen, non-obvious change effects, interacting external systems. Prefer named constants over inline values.

### M-LOG-STRUCTURED
**Use Structured Logging with Message Templates**

Use structured events with named properties following the messagetemplates.org spec. Avoid string formatting; defer formatting until viewing. Name events hierarchically: `<component>.<operation>.<state>`. Follow OpenTelemetry semantic conventions. Redact sensitive data.

---

## Library / Interoperability

### M-TYPES-SEND
**Types are Send**

Public types should be `Send` for compatibility with Tokio and other async runtimes. All futures must be `Send`. Non-`Send` types "infect futures turning them `!Send` if held across `.await` points." Atomic operations have minimal performance impact.

Exception: Types with instantaneous, ad-hoc usage patterns that are never held across `.await` boundaries may be `!Send`.

### M-ESCAPE-HATCHES
**Native Escape Hatches**

Types wrapping native handles should provide `unsafe` conversion methods for FFI:
- `unsafe fn from_native()` — constructs from external handles
- `fn into_native()` — permanent conversion
- `fn to_native()` — temporary conversion

### M-DONT-LEAK-TYPES
**Don't Leak External Types**

Priority hierarchy for public API types:
1. Prefer `std` types
2. Umbrella crates may leak sibling crate types
3. Feature-gated external types are acceptable
4. Unfeature-gated external types only if providing substantial benefit

---

## Library / UX

### M-SIMPLE-ABSTRACTIONS
**Abstractions Don't Visibly Nest**

Avoid exposing deeply nested or complex parametrized types in public APIs. Primary service APIs should not nest; if they do, only one level deep. Users should never encounter `Foo<Bar<FooBar>>` from your API.

Consider: Will users need to name this type? Does it primarily compose with non-user types? Do type parameters have complex bounds?

### M-AVOID-WRAPPERS
**Avoid Smart Pointers and Wrappers in APIs**

Hide generic wrappers (`Rc<T>`, `Arc<T>`, `Box<T>`, `RefCell<T>`) behind clean APIs using simple types (`&T`, `&mut T`, `T`).

```rust
// Good
pub fn process_data(data: &Data) -> State { ... }

// Bad
pub fn process_shared(data: Arc<Mutex<Shared>>) -> Box<Processed> { ... }
```

### M-DI-HIERARCHY
**Prefer Types over Generics, Generics over Dyn Traits**

Escalation ladder for dependency injection:
1. **Enums** for testing (sans-IO pattern)
2. **Narrow traits** for custom user implementations (`StoreObject`, `LoadObject`)
3. **Generic parameters** when nesting isn't excessive
4. **Dyn trait with wrapper** only when generics cause nesting problems

```rust
// Step 3: Generic parameter
struct MyService<T: DataAccess> { db: T }

// Step 4: Dyn trait wrapper (last resort)
struct DynamicDataAccess(Arc<dyn DataAccess>);
```

### M-ERRORS-CANONICAL-STRUCTS
**Errors are Canonical Structs**

Error types must include:
- `Backtrace` for debugging complex/async code
- Upstream error cause when applicable
- Helper methods for error-specific information (`is_io()`, `is_protocol()`)

Keep `ErrorKind` enums private; expose `is_xxx()` methods instead. Implement `std::error::Error`. `Backtrace::capture()` has ~4us overhead and only captures when explicitly enabled.

```rust
pub struct ConfigurationError {
    backtrace: Backtrace,
}

impl ConfigurationError {
    pub fn config_file(&self) -> &Path { }
    pub fn is_io(&self) -> bool { ... }
}
```

### M-INIT-BUILDER
**Complex Type Construction has Builders**

Use inherent methods for 0-2 optional parameters; use builders for 4+ permutations.

```rust
impl Foo {
    pub fn builder(deps: impl Into<FooDeps>) -> FooBuilder { ... }
}

impl FooBuilder {
    pub fn a(mut self, a: A) -> Self { ... }
    pub fn build(self) -> Foo { ... }
}
```

Required parameters go in the builder constructor via a deps struct. Provide dedicated runtime-specific builders when needed (`builder_tokio()`).

### M-INIT-CASCADED
**Complex Initialization Hierarchies are Cascaded**

Types requiring 4+ parameters should group parameters semantically:

```rust
// Bad: flat parameters
pub fn new(bank_name: &str, customer_name: &str, currency_name: &str, amount: u64) -> Self

// Good: semantic grouping
pub fn new(account: Account, amount: Currency) -> Self
```

### M-SERVICES-CLONE
**Services are Clone**

Service types implement shared-ownership `Clone` via `Arc<Inner>`:

```rust
#[derive(Clone)]
pub struct ServiceCommon {
    inner: Arc<ServiceCommonInner>
}
```

Clone should not create fat copies — it clones the `Arc` pointer only.

### M-IMPL-ASREF
**Accept `impl AsRef<>` Where Feasible**

| Instead of | Accept |
|---|---|
| `&str`, `String` | `impl AsRef<str>` |
| `&Path`, `PathBuf` | `impl AsRef<Path>` |
| `&[u8]`, `Vec<u8>` | `impl AsRef<[u8]>` |

Avoid `AsRef` bounds on struct fields; use concrete types like `String` there.

### M-IMPL-RANGEBOUNDS
**Accept `impl RangeBounds<>` Where Feasible**

Use `impl RangeBounds<usize>` instead of `(low, high)` tuples. Supports all range forms: `1..3`, `1..`, `..`, etc.

### M-IMPL-IO
**Accept `impl Read`/`impl Write` Where Feasible (Sans IO)**

Functions performing one-shot I/O should accept generic I/O traits:
- Synchronous: `std::io::Read`, `std::io::Write`
- Async multi-runtime: `futures::io::AsyncRead` and similar

This untangles business logic from I/O logic.

### M-ESSENTIAL-FN-INHERENT
**Essential Functionality Should be Inherent**

Implement core functionality as inherent methods; have trait implementations forward to them:

```rust
impl HttpClient {
    fn download_file(&self, url: impl AsRef<str>) { /* core logic */ }
}

impl Download for HttpClient {
    fn download_file(&self, url: impl AsRef<str>) {
        Self::download_file(self, url) // forward to inherent
    }
}
```

This ensures users can call methods without importing traits.

---

## Library / Resilience

### M-MOCKABLE-SYSCALLS
**I/O and System Calls Are Mockable**

Operations that are non-deterministic, rely on external state, or depend on hardware should be mockable. Use non-public enums to dispatch between native and mocked implementations:

```rust
pub struct Library { some_core: LibraryCore }

impl Library {
    pub fn new() -> Self { ... }
    pub fn new_mocked() -> (Self, MockCtrl) { ... }
}

enum LibraryCore {
    Native,
    #[cfg(feature = "test-util")]
    Mocked(mock::MockCtrl)
}
```

### M-TEST-UTIL
**Test Utilities are Feature Gated**

Guard all test-related features behind `test-util` feature flag: mocking, sensitive data inspection, safety overrides, fake data generation.

### M-STRONG-TYPES
**Use the Proper Type Family**

Use the strongest type available as early as possible. OS-related operations should use `PathBuf`/`Path` instead of `String`/`&str`.

### M-NO-GLOB-REEXPORTS
**Don't Glob Re-Export Items**

Use explicit re-exports: `pub use foo::{A, B, C};` to prevent accidentally leaking unintended types.

### M-AVOID-STATICS
**Avoid Statics**

Rust's version resolution can create multiple instantiations of the same crate, leading to separate static instances. Use statics only for performance optimization, not when consistency matters for correctness.

---

## Library / Building

### M-OOBE
**Libraries Work Out of the Box**

Libraries must build on all Tier 1 platforms with only `cargo`, Rust, and standard tooling. No additional prerequisites. If specialized tools are needed, run them during publishing, not user builds.

### M-SYS-CRATES
**Native `-sys` Crates Compile Without Dependencies**

Govern native builds via `build.rs` using the `cc` crate. Avoid Makefiles. Make external tools optional. Embed upstream source with verification. Pre-generate `bindgen` glue when feasible.

### M-FEATURES-ADDITIVE
**Features are Additive**

All features must be additive; any combination must work. Never introduce `no-std` (use `std` instead). Adding a feature must not disable or modify existing public APIs.

---

## Applications

### M-MIMALLOC-APP
**Use Mimalloc for Apps**

```rust
use mimalloc::MiMalloc;

#[global_allocator]
static GLOBAL: MiMalloc = MiMalloc;
```

Can yield up to 25% benchmark improvements on allocating hot paths.

### M-APP-ERROR
**Applications May Use Anyhow or Derivatives**

Application-level code may use anyhow or eyre instead of custom error types. Use a single application-level error type consistently. Libraries used by multiple crates must still follow M-ERRORS-CANONICAL-STRUCTS.

---

## FFI

### M-ISOLATE-DLL-STATE
**Isolate DLL State Between FFI Libraries**

When loading multiple Rust DLLs in one application, only share "portable" state — data that is `#[repr(C)]` or similarly well-defined and:
- Has no interaction with `static` or thread-local variables
- Has no interaction with `TypeId`
- Contains no non-portable data

Never share between DLLs: `String`, `Vec<u8>`, `Box<T>`, types relying on library statics, non-`#[repr(C)]` structs.

---

## Safety

### M-UNSAFE
**Unsafe Needs Reason, Should be Avoided**

Valid reasons for `unsafe`:
- Novel abstractions (new smart pointers, allocators)
- Performance optimization (`.get_unchecked()`)
- FFI and platform calls

Invalid uses: shortening safe code, bypassing `Send` bounds, circumventing lifetimes via `transmute`.

Requirements for novel abstractions: verify no alternative, keep minimal, test against adversarial code, include safety reasoning, pass Miri verification.

### M-UNSAFE-IMPLIES-UB
**Unsafe Implies Undefined Behavior**

Mark functions `unsafe` only when misuse creates UB risk, not for general danger. `unsafe fn print_string(x: *const String)` is valid; `unsafe fn delete_database()` is not.

### M-UNSOUND
**All Code Must be Sound**

Sound code marked `safe` cannot produce undefined behavior regardless of how it's called. Unsound code is never acceptable. If something cannot be safely encapsulated, expose `unsafe` functions with documentation.

---

## Performance

### M-THROUGHPUT
**Optimize for Throughput, Avoid Empty Cycles**

Key metric: items per CPU cycle. Partition work into chunks. Allow threads/tasks to work independently. Sleep or yield when idle. Design APIs for batched operations. Exploit CPU caches and data locality. Use shared state only when sharing costs less than recomputation.

### M-HOTPATH
**Identify, Profile, Optimize the Hot Path Early**

Determine early if your crate is performance-relevant. Create benchmarks with criterion or divan. Run profilers (Intel VTune, Superluminal) regularly. Enable debug symbols in bench profile: `[profile.bench] debug = 1`. Common issues: frequent reallocation, string cloning, repeated re-hashing — optimizing these can yield 15-50% gains.

### M-YIELD-POINTS
**Long-Running Tasks Should Have Yield Points**

CPU-bound tasks should call `yield_now().await` at intervals. Use `has_budget_remaining()` for unpredictable durations. Target 10-100us of CPU-bound work between yield points to keep task-switching overhead under 1%.

---

## Documentation

### M-FIRST-DOC-SENTENCE
**First Sentence is One Line; ~15 Words**

The opening sentence becomes the summary in module docs. Keep it on one line to prevent awkward wrapping.

### M-MODULE-DOCS
**Has Module Documentation**

All public library modules must have `//!` docs covering: purpose, usage context, code examples, specifications, side effects, and implementation details. Model after `std::fmt`, `std::pin`, `std::option`.

### M-CANONICAL-DOCS
**Documentation Has Canonical Sections**

Required sections: summary (always), extended docs (encouraged), Examples (strongly encouraged), Errors (when returning `Result`), Panics (when applicable), Safety (for `unsafe`), Abort (when possible).

Use inline parameter descriptions, not parameter tables:
```rust
/// Copies a file from `src` to `dst`.
fn copy(src: File, dst: File) {}
```

### M-DOC-INLINE
**Mark `pub use` Items with `#[doc(inline)]`**

```rust
#[doc(inline)]
pub use foo::Foo;
```

Applies to crate-internal items only; keep external types opaque.

---

## AI

### M-DESIGN-FOR-AI
**Design with AI Use in Mind**

Rust's strong type system helps compensate for AI agents' lack of deep understanding through comprehensive compiler checks. Design for AI by:
- Following idiomatic Rust API patterns
- Writing thorough documentation targeting "solid, but not expert" Rust knowledge
- Including directly usable examples
- Implementing strong types (avoid primitive obsession)
- Making APIs testable with mocks/fakes/feature flags
- Maintaining good test coverage of observable behavior
