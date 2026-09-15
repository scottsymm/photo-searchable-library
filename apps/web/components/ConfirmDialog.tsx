"use client";

import { useEffect, useRef } from "react";

interface ConfirmDialogProps {
  open: boolean;
  title: string;
  description: string;
  confirmLabel: string;
  onConfirm: () => void;
  onCancel: () => void;
}

export function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const cancelRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    cancelRef.current?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onCancel();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [open, onCancel]);

  if (!open) return null;

  return <div className="dialogBackdrop" role="presentation">
    <div className="dialog" role="dialog" aria-modal="true" aria-labelledby="confirm-dialog-title" aria-describedby="confirm-dialog-description">
      <div className="eyebrow">Confirm action</div>
      <h2 id="confirm-dialog-title">{title}</h2>
      <p id="confirm-dialog-description" className="muted">{description}</p>
      <div className="dialogActions">
        <button ref={cancelRef} className="button secondary" onClick={onCancel}>Cancel</button>
        <button className="button" onClick={onConfirm}>{confirmLabel}</button>
      </div>
    </div>
  </div>;
}
