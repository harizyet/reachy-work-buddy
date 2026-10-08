import { useEffect, useRef, type ReactNode } from 'react';

// A modal built on the native <dialog>, so focus containment, Escape and the backdrop come from the
// browser. jsdom has no showModal(), so tests fall back to the open attribute.
export function Dialog({ open, title, onClose, children }: { open: boolean; title: string; onClose: () => void; children: ReactNode }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) {
      if (typeof dialog.showModal === 'function') dialog.showModal();
      else dialog.setAttribute('open', '');
    }
    if (!open && dialog.open) {
      if (typeof dialog.close === 'function') dialog.close();
      else dialog.removeAttribute('open');
    }
  }, [open]);
  return (
    <dialog
      ref={ref}
      aria-label={title}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      className="m-auto w-[min(26rem,calc(100vw-2rem))] rounded-lg border border-[var(--border)] bg-[var(--surface)] p-0 text-[var(--text)] backdrop:bg-black/40"
    >
      {open && <div className="p-4">{children}</div>}
    </dialog>
  );
}
