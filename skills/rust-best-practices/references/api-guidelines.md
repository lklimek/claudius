# Rust API Guidelines — Detailed Reference

Source: https://rust-lang.github.io/api-guidelines/

Use this file when you need detailed guidance on any C-prefixed checklist item.
Each section includes the rationale, requirements, and code examples.

## Table of Contents

- [Naming](#naming)
  - [C-CASE](#c-case), [C-CONV](#c-conv), [C-GETTER](#c-getter), [C-ITER](#c-iter), [C-ITER-TY](#c-iter-ty), [C-FEATURE](#c-feature), [C-WORD-ORDER](#c-word-order)
- [Interoperability](#interoperability)
  - [C-COMMON-TRAITS](#c-common-traits), [C-CONV-TRAITS](#c-conv-traits), [C-COLLECT](#c-collect), [C-SERDE](#c-serde), [C-SEND-SYNC](#c-send-sync), [C-GOOD-ERR](#c-good-err), [C-NUM-FMT](#c-num-fmt), [C-RW-VALUE](#c-rw-value)
- [Macros](#macros)
  - [C-EVOCATIVE](#c-evocative), [C-MACRO-ATTR](#c-macro-attr), [C-ANYWHERE](#c-anywhere), [C-MACRO-VIS](#c-macro-vis), [C-MACRO-TY](#c-macro-ty)
- [Documentation](#documentation)
  - [C-CRATE-DOC](#c-crate-doc), [C-EXAMPLE](#c-example), [C-QUESTION-MARK](#c-question-mark), [C-FAILURE](#c-failure), [C-LINK](#c-link), [C-METADATA](#c-metadata), [C-RELNOTES](#c-relnotes), [C-HIDDEN](#c-hidden)
- [Predictability](#predictability)
  - [C-SMART-PTR](#c-smart-ptr), [C-CONV-SPECIFIC](#c-conv-specific), [C-METHOD](#c-method), [C-NO-OUT](#c-no-out), [C-OVERLOAD](#c-overload), [C-DEREF](#c-deref), [C-CTOR](#c-ctor)
- [Flexibility](#flexibility)
  - [C-INTERMEDIATE](#c-intermediate), [C-CALLER-CONTROL](#c-caller-control), [C-GENERIC](#c-generic), [C-OBJECT](#c-object)
- [Type Safety](#type-safety)
  - [C-NEWTYPE](#c-newtype), [C-CUSTOM-TYPE](#c-custom-type), [C-BITFLAG](#c-bitflag), [C-BUILDER](#c-builder)
- [Dependability](#dependability)
  - [C-VALIDATE](#c-validate), [C-DTOR-FAIL](#c-dtor-fail), [C-DTOR-BLOCK](#c-dtor-block)
- [Debuggability](#debuggability)
  - [C-DEBUG](#c-debug), [C-DEBUG-NONEMPTY](#c-debug-nonempty)
- [Future Proofing](#future-proofing)
  - [C-SEALED](#c-sealed), [C-STRUCT-PRIVATE](#c-struct-private), [C-NEWTYPE-HIDE](#c-newtype-hide), [C-STRUCT-BOUNDS](#c-struct-bounds)
- [Necessities](#necessities)
  - [C-STABLE](#c-stable), [C-PERMISSIVE](#c-permissive)

---

## Naming

### C-CASE
**Casing Conforms to RFC 430**

| Construct | Convention | Example |
|---|---|---|
| Types, traits, enum variants | `UpperCamelCase` | `HttpClient` |
| Modules, functions, methods, macros, variables | `snake_case` | `read_file` |
| Constants, statics | `SCREAMING_SNAKE_CASE` | `MAX_RETRIES` |
| Type parameters | Concise `UpperCamelCase` | `T`, `K`, `V` |
| Lifetimes | Short lowercase | `'a`, `'de` |

Acronyms in CamelCase count as one word: `Uuid` not `UUID`. In snake_case: `is_xid_start`.
Avoid `-rs` or `-rust` suffixes in crate names.

### C-CONV
**Ad-hoc Conversions Follow `as_`, `to_`, `into_` Conventions**

| Prefix | Cost | Ownership |
|---|---|---|
| `as_` | Free | borrowed -> borrowed |
| `to_` | Expensive | borrowed -> borrowed/owned; owned -> owned (Copy) |
| `into_` | Variable | owned -> owned (non-Copy) |

Examples: `as_bytes()` (free view), `to_lowercase()` (produces owned String), `into_bytes()` (extracts Vec from String). Wrapper types use `into_inner()`.

Place `mut` qualifier as in return type: `as_mut_slice` not `as_slice_mut`.

### C-GETTER
**Getter Names Follow Rust Convention**

Omit `get_` prefix. Use field name directly:
```rust
pub fn first(&self) -> &First { &self.first }
pub fn first_mut(&mut self) -> &mut First { &mut self.first }
```

Exception: Use `get` for single obvious retrievals like `Cell::get`. Provide `_unchecked` variants for methods with runtime validation.

### C-ITER
**Iterator Method Naming**

```rust
fn iter(&self) -> Iter           // yields &U
fn iter_mut(&mut self) -> IterMut // yields &mut U
fn into_iter(self) -> IntoIter   // yields U
```

Applies to conceptually homogeneous collections only. Counterexample: `str` provides `bytes()` and `chars()` instead.

### C-ITER-TY
**Iterator Type Names Match Producing Methods**

`into_iter()` returns `IntoIter`, `keys()` returns `Keys`. Type names gain clarity with module prefix: `vec::IntoIter`.

### C-FEATURE
**Feature Names Free of Placeholder Words**

No `use-abc`, `with-abc`, `no-abc`. For optional std: `default = ["std"]`, `std = []`.
Feature names should match dependency names. Cargo enforces additive features.

### C-WORD-ORDER
**Names Use Consistent Word Order**

Error types follow verb-object-error: `ParseBoolError`, `JoinPathsError`, `RecvTimeoutError`.

---

## Interoperability

### C-COMMON-TRAITS
**Types Eagerly Implement Common Traits**

Due to the orphan rule, implement all applicable traits in the type's crate:
- Copy, Clone, Eq, PartialEq, Ord, PartialOrd, Hash, Debug, Display, Default

Types should implement both `Default` and parameterless `new()` when semantically appropriate.

### C-CONV-TRAITS
**Conversions Use Standard Traits**

Implement `From<T>` and `TryFrom<T>` — never implement `Into<T>` or `TryInto<T>` directly (blanket implementations exist). Also implement `AsRef<T>` and `AsMut<T>` where appropriate.

### C-COLLECT
**Collections Implement FromIterator and Extend**

These enable `collect()`, `partition()`, `unzip()`. `FromIterator` creates new collections; `Extend` adds to existing ones.

### C-SERDE
**Data Structures Implement Serialize/Deserialize**

Gate behind optional `"serde"` feature to avoid compilation costs:
```toml
serde = { version = "1.0", optional = true }
```

### C-SEND-SYNC
**Types Are Send and Sync Where Possible**

Auto-implemented when appropriate. For types using raw pointers, verify thread-safety with tests.

### C-GOOD-ERR
**Error Types Are Meaningful and Well-Behaved**

Must implement `std::error::Error + Send + Sync`. `Display` output: lowercase, no trailing punctuation. Never use `()` as error type. Don't implement deprecated `Error::description()`.

### C-NUM-FMT
**Binary Types Provide Hex/Octal/Binary Formatting**

Implement `UpperHex`, `LowerHex`, `Octal`, `Binary` for bitwise-manipulable types, especially bitflag types.

### C-RW-VALUE
**Generic Reader/Writer Functions Take by Value**

Accept `R: Read` and `W: Write` by value. Blanket implementations allow `&mut` references to be passed, supporting composable chains.

---

## Macros

### C-EVOCATIVE
**Input Syntax is Evocative of the Output**

Mirror output syntax in macro input. Use keywords and punctuation similar to generated output. Prefix struct declarations with `struct`. Follow Rust conventions.

### C-MACRO-ATTR
**Item Macros Compose Well with Attributes**

Support `#[cfg(...)]` and `#[derive(...)]` on individual macro-generated items.

### C-ANYWHERE
**Item Macros Work Anywhere Items Are Allowed**

Test at both module scope and function scope. Beware `super::` references failing in function scope.

### C-MACRO-VIS
**Item Macros Support Visibility Specifiers**

Private by default, public with `pub`. Distinguish `struct Foo {}` from `pub struct Foo {}`.

### C-MACRO-TY
**Type Fragments Are Flexible**

Macros with `$t:ty` must work with: primitives (`u8`), relative paths (`m::Data`), absolute paths (`::base::Data`), upward paths (`super::Data`), generics (`Vec<String>`).

---

## Documentation

### C-CRATE-DOC
**Crate-Level Docs Are Thorough with Examples**

Root-level module documentation must explain purpose and include practical examples.

### C-EXAMPLE
**All Public Items Have a Rustdoc Example**

Examples should explain motivations, not just mechanics. Linking to examples on related items is acceptable.

### C-QUESTION-MARK
**Examples Use `?`, Not `try!`, Not `unwrap`**

```rust
/// ```rust
/// # use std::error::Error;
/// # fn main() -> Result<(), Box<dyn Error>> {
/// your_code()?;
/// #     Ok(())
/// # }
/// ```
```

Lines prefixed with `#` compile in `cargo test` but are invisible in docs.

### C-FAILURE
**Function Docs Include Error, Panic, and Safety Sections**

- **Errors**: Document error conditions
- **Panics**: Document panic conditions
- **Safety**: For `unsafe` functions, document all caller invariants

### C-LINK
**Prose Contains Hyperlinks**

Use `` [`TypeName`] `` with link targets. Methods: `#method.name`. Other types: `trait.Name.html`. Parent modules: `../enum.Value.html`.

### C-METADATA
**Cargo.toml Includes Common Metadata**

Required: authors, description, license, repository, keywords, categories. Optional: documentation (if not docs.rs), homepage (if distinct from repo).

### C-RELNOTES
**Release Notes Document Significant Changes**

Clearly identify breaking changes. Use annotated Git tags for every crates.io release.

### C-HIDDEN
**Rustdoc Does Not Show Unhelpful Details**

Use `#[doc(hidden)]` for irrelevant trait implementations. Use `pub(crate)` for internal helpers.

---

## Predictability

### C-SMART-PTR
**Smart Pointers Do Not Add Inherent Methods**

Define operations as static methods to avoid ambiguity with wrapped type's methods. Example: `Box::into_raw` is static, not inherent.

### C-CONV-SPECIFIC
**Conversions Live on the Most Specific Type**

Place conversion methods on the more specific type. Prefer `to_`/`as_`/`into_` over `from_` patterns.

### C-METHOD
**Functions with a Clear Receiver Are Methods**

Methods don't need imports, support autoborrowing, and clarify available operations on a type.

### C-NO-OUT
**Functions Do Not Take Out-Parameters**

Return multiple values via tuples or structs. Exception: functions meant to reuse caller-owned buffers.

### C-OVERLOAD
**Operator Overloads Are Unsurprising**

Implement only for operations resembling mathematical counterparts with expected properties.

### C-DEREF
**Only Smart Pointers Implement Deref/DerefMut**

Reserved for: `Box<T>`, `String`, `Rc<T>`, `Arc<T>`, `Cow<'a, T>`.

### C-CTOR
**Constructors Are Static, Inherent Methods**

Primary: `new()`. Secondary: `_with_foo` suffixes or domain-specific names (`open()`, `connect()`). `from_` constructors can be `unsafe`, accept extra args, or disambiguate — unlike `From` trait.

---

## Flexibility

### C-INTERMEDIATE
**Functions Expose Intermediate Results**

Examples: `Vec::binary_search` returns index OR insertion position. `String::from_utf8` returns byte offset on error. `HashMap::insert` returns preexisting value.

### C-CALLER-CONTROL
**Caller Decides Where to Copy and Place Data**

Functions requiring ownership take by value; those that don't, borrow. Don't bound on `Copy` unnecessarily.

### C-GENERIC
**Functions Minimize Assumptions Using Generics**

```rust
// Preferred: works with any iterator
fn foo<I: IntoIterator<Item = i64>>(iter: I) { }

// Not: restricted to slices
fn foo(data: &[i64]) { }
```

Standard library example: `File::open` takes `AsRef<Path>`.

### C-OBJECT
**Traits Are Object-Safe If Useful as Trait Objects**

Use `where Self: Sized` to exclude generic methods from trait objects:
```rust
trait MyTrait {
    fn object_safe(&self, i: i32);
    fn not_object_safe<T>(&self, t: T) where Self: Sized;
}
```

---

## Type Safety

### C-NEWTYPE
**Newtypes Provide Static Distinctions**

```rust
struct Miles(pub f64);
struct Kilometers(pub f64);
```

Prevents accidental confusion (like the Mars Climate Orbiter incident).

### C-CUSTOM-TYPE
**Arguments Convey Meaning Through Types**

```rust
// Good: clear intent
let w = Widget::new(Small, Round);

// Bad: opaque booleans
let w = Widget::new(true, false);
```

### C-BITFLAG
**Flag Sets Use `bitflags`, Not Enums**

```rust
bitflags! {
    struct Flags: u32 {
        const FLAG_A = 0b00000001;
        const FLAG_B = 0b00000010;
    }
}
```

### C-BUILDER
**Builders Enable Complex Value Construction**

Non-consuming builders (preferred) take `&self` in terminal method. Consuming builders take `self`. Builder takes only required params; configuration methods return `self` for chaining.

---

## Dependability

### C-VALIDATE
**Functions Validate Their Arguments**

Validation methods in order of preference:
1. **Static enforcement** via type system (compile-time)
2. **Dynamic enforcement** at runtime
3. **Dynamic with `debug_assert!`** (dev-only)
4. **Dynamic with opt-out** (`_unchecked` variants)

### C-DTOR-FAIL
**Destructors Never Fail**

Provide separate `close()` returning `Result` for explicit cleanup. Destructors should perform teardown silently.

### C-DTOR-BLOCK
**Destructors That May Block Have Alternatives**

Offer separate methods for preparing nonblocking teardown.

---

## Debuggability

### C-DEBUG
**All Public Types Implement Debug**

Standard expectation for public APIs. Rare exceptions only.

### C-DEBUG-NONEMPTY
**Debug Representation Is Never Empty**

Empty string displays as `"\"\""`. Empty vector displays as `[]`. Always visually distinct from nothing.

---

## Future Proofing

### C-SEALED
**Sealed Traits Protect Against Downstream Implementations**

```rust
mod private {
    pub trait Sealed {}
}

pub trait TheTrait: private::Sealed {
    fn method(&self);
}
```

Allows adding methods in non-breaking releases. Document that the trait is sealed.

### C-STRUCT-PRIVATE
**Structs Have Private Fields**

Public fields pin representation choices and prevent validation/invariants. Use getter/setter methods.

### C-NEWTYPE-HIDE
**Newtypes Encapsulate Implementation Details**

Wrap complex types to hide representation. Consider `impl Trait` for return types as an alternative.

### C-STRUCT-BOUNDS
**Data Structures Do Not Duplicate Derived Trait Bounds**

Adding trait bounds to structures is a breaking change. Let `derive` handle them. Don't add bounds for: Clone, PartialEq, PartialOrd, Debug, Display, Default, Error, Serialize, Deserialize, DeserializeOwned.

Exceptions: bound references an associated type, bound is `?Sized`, `Drop` impl requires bounds.

---

## Necessities

### C-STABLE
**Public Dependencies of a Stable Crate Are Stable**

A crate cannot reach 1.0 without stable public dependencies. Public dependencies include types exposed through `From` implementations.

### C-PERMISSIVE
**Crate and Dependencies Have a Permissive License**

Recommended: dual MIT/Apache-2.0 (`"MIT OR Apache-2.0"`). Include LICENSE-APACHE and LICENSE-MIT files. Avoid Apache-only licensing.
