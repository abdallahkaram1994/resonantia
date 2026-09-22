import type { Era, MediaType } from "./api";

export const ALL_TYPES: MediaType[] = ["film", "game", "album"];

// Albums are switched off by default: a small number of them sit disproportionately close to
// many unrelated queries in the shared embedding space ("hubness"), confirmed on the real catalog
// (one album was the nearest album match for 20% of a 500-film sample), crowding out legitimate
// album matches in blended results. Still fully searchable by checking the box back on.
export const DEFAULT_TYPES: MediaType[] = ["film", "game"];

const TYPE_LABELS: Record<MediaType, string> = { film: "Films", game: "Games", album: "Albums" };

// SPEC section 7.2: decade chips. Labels match the SPEC's own shorthand ("80s, 90s, 00s…").
export const DECADES: { label: string; era: Era }[] = [
  { label: "50s", era: { start: 1950, end: 1959 } },
  { label: "60s", era: { start: 1960, end: 1969 } },
  { label: "70s", era: { start: 1970, end: 1979 } },
  { label: "80s", era: { start: 1980, end: 1989 } },
  { label: "90s", era: { start: 1990, end: 1999 } },
  { label: "00s", era: { start: 2000, end: 2009 } },
  { label: "10s", era: { start: 2010, end: 2019 } },
  { label: "20s", era: { start: 2020, end: 2029 } },
];

function sameEra(a: Era, b: Era): boolean {
  return a.start === b.start && a.end === b.end;
}

export function hasEra(eras: Era[], era: Era): boolean {
  return eras.some((e) => sameEra(e, era));
}

export default function SearchFilters({
  types,
  eras,
  onTypesChange,
  onErasChange,
}: {
  types: MediaType[];
  eras: Era[];
  onTypesChange: (types: MediaType[]) => void;
  onErasChange: (eras: Era[]) => void;
}) {
  function toggleType(type: MediaType) {
    if (types.includes(type)) {
      if (types.length === 1) return; // at least one type must always stay chosen
      onTypesChange(types.filter((t) => t !== type));
    } else {
      onTypesChange(ALL_TYPES.filter((t) => t === type || types.includes(t)));
    }
  }

  function toggleEra(era: Era) {
    onErasChange(hasEra(eras, era) ? eras.filter((e) => !sameEra(e, era)) : [...eras, era]);
  }

  return (
    <div className="mt-4 flex flex-col gap-3 text-sm">
      <fieldset className="flex flex-wrap items-center gap-3">
        <legend className="sr-only">Media types</legend>
        {ALL_TYPES.map((type) => {
          const checked = types.includes(type);
          const isLastOne = checked && types.length === 1;
          return (
            <label
              key={type}
              className={`flex items-center gap-1.5 ${isLastOne ? "opacity-60" : ""}`}
            >
              <input
                type="checkbox"
                checked={checked}
                onChange={() => toggleType(type)}
                disabled={isLastOne}
              />
              {TYPE_LABELS[type]}
            </label>
          );
        })}
      </fieldset>
      <fieldset className="flex flex-wrap gap-1.5">
        <legend className="sr-only">Decade</legend>
        {DECADES.map(({ label, era }) => {
          const active = hasEra(eras, era);
          return (
            <button
              key={label}
              type="button"
              aria-pressed={active}
              onClick={() => toggleEra(era)}
              className={`rounded-full border px-2.5 py-0.5 text-xs ${
                active
                  ? "border-gray-900 bg-gray-900 text-white"
                  : "border-gray-300 text-gray-600"
              }`}
            >
              {label}
            </button>
          );
        })}
      </fieldset>
    </div>
  );
}
