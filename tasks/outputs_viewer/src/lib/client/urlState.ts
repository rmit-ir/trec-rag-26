"use client";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import * as React from "react";

/**
 * URL search-param state: read a param and update it in place (replace, no
 * scroll) so every meaningful view state survives refresh / link sharing.
 */
export function useUrlState() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const get = React.useCallback(
    (key: string): string | null => searchParams.get(key),
    [searchParams],
  );

  const setMany = React.useCallback(
    (updates: Record<string, string | null>) => {
      const next = new URLSearchParams(searchParams.toString());
      for (const [k, v] of Object.entries(updates)) {
        if (v === null || v === "") next.delete(k);
        else next.set(k, v);
      }
      const qs = next.toString();
      router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
    },
    [router, pathname, searchParams],
  );

  const set = React.useCallback(
    (key: string, value: string | null) => setMany({ [key]: value }),
    [setMany],
  );

  return { get, set, setMany, searchParams };
}
