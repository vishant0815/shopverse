// A small bar chart drawn with plain HTML: one bar per day, today's bar in red.
// No chart library needed for seven bars.

function dayLabel(isoDate, isToday) {
  if (isToday) return "Today";
  return new Date(`${isoDate}T00:00:00Z`).toLocaleDateString("en-GB", { weekday: "short", timeZone: "UTC" });
}

export default function UnitsChart({ days }) {
  const max = Math.max(1, ...days.map((d) => d.units));
  const total = days.reduce((sum, d) => sum + d.units, 0);

  return (
    <figure>
      <div className="flex h-44 items-end gap-3 px-1" role="img" aria-label={`Units sold over the last ${days.length} days: ${total} in total`}>
        {days.map((day, index) => {
          const isToday = index === days.length - 1;
          const height = day.units === 0 ? 3 : Math.max(8, (day.units / max) * 100);
          return (
            <div key={day.date} className="flex h-full flex-1 flex-col items-center justify-end gap-2">
              <span className="text-xs font-semibold text-ink-soft">{day.units || ""}</span>
              <span
                className={`block w-full rounded-t-[10px] rounded-b-[4px] ${
                  isToday ? "bg-power shadow-[var(--power-glow)]" : "bg-[image:var(--metal)] shadow-[3px_3px_6px_var(--shadow-dark)]"
                } ${day.units === 0 ? "opacity-30" : ""}`}
                style={{ height: `${height}%` }}
              />
              <span className="text-xs text-ink-soft">{dayLabel(day.date, isToday)}</span>
            </div>
          );
        })}
      </div>
      <figcaption className="sr-only">
        {days.map((d) => `${d.date}: ${d.units}`).join(", ")}
      </figcaption>
    </figure>
  );
}
