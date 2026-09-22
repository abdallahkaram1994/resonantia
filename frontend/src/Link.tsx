import type { MouseEvent, ReactNode } from "react";
import { navigate } from "./router";

/** A same-origin link that navigates without a full page reload, but is still a real `<a>`: it
 * works with the keyboard, shows the target in the status bar, and a modified click (open in a
 * new tab, and so on) still behaves normally. */
export default function Link({
  to,
  children,
  className,
}: {
  to: string;
  children: ReactNode;
  className?: string;
}) {
  function handleClick(event: MouseEvent<HTMLAnchorElement>) {
    const isPlainLeftClick = event.button === 0;
    const isModified = event.metaKey || event.ctrlKey || event.shiftKey || event.altKey;
    if (!isPlainLeftClick || isModified) return;
    event.preventDefault();
    navigate(to);
  }

  return (
    <a href={to} onClick={handleClick} className={className}>
      {children}
    </a>
  );
}
