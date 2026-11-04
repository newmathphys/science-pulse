/-
  Science Pulse — формальные инварианты (Lean 4, ядро без mathlib).

  Машинная проверка:  lean formal/Invariants.lean
  Исполняемый эквивалент: science_pulse/invariants.py (см. docs/FORMAL.md).

  Доказательства без `sorry`: все теоремы замкнуты.
-/

namespace SciencePulse

/-! ## Модель статуса поста (INV-4) -/

/-- Статус поста в очереди. Неизвестных статусов нет по построению типа. -/
inductive Status where
  | ready
  | publishing
  | published
  | failed
  deriving DecidableEq, Repr

/-- Публикация разрешена только из состояния ready. -/
def canPublish : Status → Bool
  | .ready => true
  | _ => false

/-- Шаг публикации: ready → published, остальные статусы не меняются. -/
def publishStep : Status → Status
  | .ready => .published
  | s => s

/-- INV-4: статус всегда принадлежит известному множеству. -/
theorem status_total (s : Status) :
    s = .ready ∨ s = .publishing ∨ s = .published ∨ s = .failed := by
  cases s <;> decide

/-- INV-1 (терминальность): повторная публикация не меняет статус. -/
theorem publishStep_idempotent (s : Status) :
    publishStep (publishStep s) = publishStep s := by
  cases s <;> rfl

/-- После публикации пост уже не в состоянии ready. -/
theorem publishStep_not_ready (s : Status) : publishStep s ≠ .ready := by
  cases s <;> simp [publishStep]

/-- Публикуется только из ready. -/
theorem publish_requires_ready (s : Status) (h : canPublish s = true) :
    s = .ready := by
  cases s <;> simp_all [canPublish]

/-! ## Идемпотентность записей (INV-1, INV-2) -/

/-- Присутствие ключа в списке записей о публикациях. -/
def contains (k : Nat) : List Nat → Bool
  | [] => false
  | x :: xs => if x = k then true else contains k xs

/-- Идемпотентная вставка: повторный запуск не создаёт дубликат. -/
def insertOnce (k : Nat) (xs : List Nat) : List Nat :=
  if contains k xs then xs else k :: xs

/-- INV-1: вставка идемпотентна (повтор не добавляет запись). -/
theorem insertOnce_idempotent (k : Nat) (xs : List Nat) :
    insertOnce k (insertOnce k xs) = insertOnce k xs := by
  by_cases h : contains k xs = true
  · simp [insertOnce, h]
  · have hf : contains k xs = false := by
      cases hc : contains k xs <;> simp_all
    have h2 : contains k (k :: xs) = true := by simp [contains]
    simp [insertOnce, hf, h2]

/-- INV-2: после вставки ключ присутствует. -/
theorem insertOnce_contains (k : Nat) (xs : List Nat) :
    contains k (insertOnce k xs) = true := by
  unfold insertOnce
  split
  · assumption
  · simp [contains]

/-! ## Учёт очереди (INV-4) -/

/-- Число постов в состоянии ready. -/
def readyCount : List Status → Nat
  | [] => 0
  | s :: rest => (if s = .ready then 1 else 0) + readyCount rest

/-- Публикация не увеличивает число готовых постов. -/
theorem publish_reduces_ready (s : Status) (rest : List Status) :
    readyCount (publishStep s :: rest) ≤ readyCount (s :: rest) := by
  cases s <;> simp [readyCount, publishStep] <;> omega

/-! ## CRDT-слияние статусов (Join-Semilattice) -/

/-- Ранг статуса: старший «сильнее» и не откатывается. -/
def rank : Status → Nat
  | .ready => 1
  | .publishing => 2
  | .failed => 3
  | .published => 4

/-- Слияние статусов: побеждает старший (монотонный join). -/
def mergeStatus (a b : Status) : Status :=
  if rank a ≥ rank b then a else b

/-- Идемпотентность: `mergeStatus a a = a`. -/
theorem mergeStatus_idempotent (a : Status) : mergeStatus a a = a := by
  cases a <;> decide

/-- Коммутативность. -/
theorem mergeStatus_comm (a b : Status) : mergeStatus a b = mergeStatus b a := by
  cases a <;> cases b <;> decide

/-- Ассоциативность. -/
theorem mergeStatus_assoc (a b c : Status) :
    mergeStatus (mergeStatus a b) c = mergeStatus a (mergeStatus b c) := by
  cases a <;> cases b <;> cases c <;> decide

/-- Сохранение `published`: слияние даёт published только если он был у одного из входов. -/
theorem mergeStatus_preserves_published (a b : Status) :
    mergeStatus a b = .published → a = .published ∨ b = .published := by
  cases a <;> cases b <;> decide

/-! ## Контур качества: гейт стандартов и карантин (INV-7) -/

/-- Если пост ещё не опубликован, published достижим только через пройденный гейт. -/
theorem published_implies_gate (s : Status) (hne : s ≠ .published)
    (h : publishStep s = .published) : canPublish s = true := by
  cases s <;> simp_all [publishStep, canPublish]

/-- Если гейт не пропускает неопубликованный пост, опубликовать его нельзя. -/
theorem gate_blocks_published (s : Status) (hne : s ≠ .published)
    (h : canPublish s = false) : publishStep s ≠ .published := by
  cases s <;> simp_all [publishStep, canPublish]

/-- Выбор готового поста в режиме round-robin. -/
def pickReady : List Status → Option Status
  | [] => none
  | s :: rest => if s = .ready then some s else pickReady rest

/-- Round-robin не «заедает»: при наличии готовых постов выбор не пуст. -/
theorem round_robin_no_deadlock (xs : List Status) (h : readyCount xs > 0) :
    pickReady xs ≠ none := by
  induction xs with
  | nil => simp [readyCount] at h
  | cons s rest ih =>
    by_cases hs : s = .ready
    · simp [pickReady, hs]
    · simp only [pickReady, hs, ite_false]
      have hr : readyCount rest > 0 := by
        have hsplit : readyCount (s :: rest) = (if s = .ready then 1 else 0) + readyCount rest := rfl
        rw [hsplit] at h
        simp [hs] at h
        omega
      exact ih hr

/-- Вердикт контура качества: пост принят или отправлен в карантин. -/
inductive Gate where
  | accepted
  | rejected
  deriving DecidableEq, Repr

/-- Шаг гейта: принятый может быть отклонён, отклонённый остаётся отклонённым. -/
def gateStep : Gate → Gate
  | .accepted => .rejected
  | .rejected => .rejected

/-- Карантин монотонен: повторное применение гейта не меняет отклонение. -/
theorem reject_monotone (g : Gate) : gateStep (gateStep g) = gateStep g := by
  cases g <;> rfl

/-- Отклонённый пост не возвращается автоматически в принятые. -/
theorem rejected_stays_rejected (g : Gate) : gateStep g = .rejected := by
  cases g <;> rfl

end SciencePulse
