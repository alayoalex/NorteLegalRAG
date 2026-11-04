// Iconos de trazo, decorativos: el texto accesible lo pone el botón que los contiene.
const PATHS = {
  plus: "M12 5v14M5 12h14",
  send: "M12 19V5M5.5 11.5 12 5l6.5 6.5",
  trash: "M4 7h16M10 11v6M14 11v6M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12M9 7V4h6v3",
  retry: "M20 11a8 8 0 1 0-2.3 5.7M20 4v7h-7",
  upload: "M12 16V4M7 9l5-5 5 5M5 20h14",
  history: "M4 6h16M4 12h10M4 18h7",
  documents: "M7 3h7l5 5v13H7zM14 3v5h5M10 13h6M10 17h6",
  close: "M6 6l12 12M18 6 6 18",
} as const;

export type IconName = keyof typeof PATHS;

export function Icon({ name }: { name: IconName }) {
  return (
    <svg
      className="icon"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={PATHS[name]} />
    </svg>
  );
}

/** Aguja de brújula: el norte de NorteLegal. */
export function NorthMark() {
  return (
    <svg className="north-mark" viewBox="0 0 24 24" aria-hidden="true">
      <path d="M12 2 16 12h-8z" fill="currentColor" />
      <path d="M12 22 8 12h8z" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
    </svg>
  );
}
