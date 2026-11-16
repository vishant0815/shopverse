// Five stars, filled up to the rating. The label is what a screen reader hears; the stars are decoration.
export const STAR_PATH = "M12 2.6l2.85 5.9 6.45.94-4.67 4.55 1.1 6.42L12 17.46l-5.73 3.01 1.1-6.42-4.67-4.55 6.45-.94z";

export default function Stars({ value, label, size = 18 }) {
  return (
    <span role="img" aria-label={label} className="inline-flex gap-0.5">
      {[1, 2, 3, 4, 5].map((star) => (
        <svg key={star} width={size} height={size} viewBox="0 0 24 24" aria-hidden="true">
          <path d={STAR_PATH} fill={star <= value ? "var(--accent)" : "var(--line)"} />
        </svg>
      ))}
    </span>
  );
}
