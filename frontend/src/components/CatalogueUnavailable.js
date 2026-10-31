export default function CatalogueUnavailable() {
  return (
    <div className="mx-auto max-w-lg py-24 text-center">
      <h1 className="text-3xl font-bold">The catalogue isn&apos;t responding</h1>
      <p className="mt-3 text-ink-soft">
        Products can&apos;t be loaded right now. Check that the products service is running
        (<code>docker compose ps</code>), then refresh this page.
      </p>
    </div>
  );
}
