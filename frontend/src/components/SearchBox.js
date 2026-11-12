"use client";

import { useRouter } from "next/navigation";
import { useEffect, useId, useState } from "react";

import { nextIndex, shouldSuggest, suggestUrl } from "@/lib/search-model";

const DEBOUNCE_MS = 150;

// The header's search box. Typing shows product suggestions; Enter on a highlighted suggestion opens that
// product, and Enter otherwise submits the form to the results page, which works without JavaScript too.
export default function SearchBox() {
  const router = useRouter();
  const listId = useId();
  const [value, setValue] = useState("");
  const [items, setItems] = useState([]);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);

  useEffect(() => {
    const query = value.trim();
    if (!shouldSuggest(query)) {
      setItems([]);
      return undefined;
    }
    const controller = new AbortController();
    const timer = setTimeout(async () => {
      try {
        const response = await fetch(suggestUrl(query), { signal: controller.signal });
        if (!response.ok) throw new Error("suggestions unavailable");
        const data = await response.json();
        setItems(data.results);
        setActive(-1);
      } catch {
        // Suggestions are a convenience: if they fail, the box still submits a normal search.
        if (!controller.signal.aborted) setItems([]);
      }
    }, DEBOUNCE_MS);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [value]);

  const showing = open && items.length > 0;

  function choose(item) {
    setOpen(false);
    router.push(`/products/${item.slug}`);
  }

  function onKeyDown(event) {
    if (event.key === "Escape") {
      setOpen(false);
      return;
    }
    if (!showing) return;
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      setActive(nextIndex(active, event.key === "ArrowDown" ? 1 : -1, items.length));
    } else if (event.key === "Enter" && active >= 0) {
      event.preventDefault();
      choose(items[active]);
    }
  }

  return (
    <div
      className="relative order-last w-full sm:order-none sm:w-auto sm:flex-1"
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false);
      }}
    >
      <form action="/products" role="search" className="inset flex w-full items-center gap-2 py-1.5 pl-4 pr-1.5">
        <label htmlFor="site-search" className="sr-only">Search products</label>
        <input
          id="site-search"
          name="search"
          type="search"
          role="combobox"
          autoComplete="off"
          aria-autocomplete="list"
          aria-expanded={showing}
          aria-controls={listId}
          aria-activedescendant={showing && active >= 0 ? `${listId}-${active}` : undefined}
          value={value}
          onChange={(event) => {
            setValue(event.target.value);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onKeyDown={onKeyDown}
          placeholder="Search phones, shirts, desks…"
          className="min-w-0 flex-1 bg-transparent py-1.5 outline-none placeholder:text-ink-soft"
        />
        <button className="btn btn-metal px-4 py-2 text-sm">Search</button>
      </form>

      {showing && (
        <div className="raised absolute left-0 right-0 top-full z-20 mt-3 p-2">
          <ul id={listId} role="listbox" aria-label="Suggestions" className="space-y-1">
            {items.map((item, index) => (
              <li
                key={item.product_id}
                id={`${listId}-${index}`}
                role="option"
                aria-selected={index === active}
                // Keeps focus in the search box, so the list doesn't close before the click lands.
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => choose(item)}
                className={`flex cursor-pointer items-center justify-between gap-3 rounded-lg px-3 py-2.5 ${
                  index === active ? "text-accent" : ""
                }`}
              >
                <span className="font-medium">{item.text}</span>
                <span className="text-xs text-ink-soft">Product</span>
              </li>
            ))}
          </ul>
          <p className="mt-2 border-t border-white/10 px-3 pt-3 text-xs text-ink-soft">
            Press Enter to see every result for “{value.trim()}”
          </p>
        </div>
      )}
    </div>
  );
}
