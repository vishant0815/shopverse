export default function CatalogueUnavailable() {
  return (
    <div className="raised mx-auto max-w-lg px-8 py-16 text-center">
      <span aria-hidden="true" className="mx-auto mb-5 block h-3 w-3 rounded-full bg-power shadow-[var(--power-glow)]" />
      <h1 className="text-3xl font-bold">The catalogue isn&apos;t responding</h1>
      <p className="mt-3 text-ink-soft">
        Products can&apos;t be loaded right now. Check that the products service is running
        (<code>docker compose ps</code>), then refresh this page.
      </p>
    </div>
  );
}
