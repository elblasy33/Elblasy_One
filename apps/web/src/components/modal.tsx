"use client";
import { XCircle } from "lucide-react";
import { useEffect, useRef, type ReactNode } from "react";

export function Modal({ title, children, onClose }: { title: string; children: ReactNode; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => { ref.current?.showModal(); }, []);
  return (
    <dialog ref={ref} onClose={onClose} className="m-auto w-[min(94vw,30rem)] rounded-[1.5rem] border border-line bg-surface p-6 text-ink shadow-card backdrop:bg-black/50">
      <div className="mb-4 flex items-center justify-between"><h2 className="text-xl font-black">{title}</h2>
        <button aria-label="close" onClick={() => ref.current?.close()} className="grid size-10 place-items-center rounded-xl hover:bg-surface2"><XCircle className="size-5 text-soft" aria-hidden /></button></div>
      {children}
    </dialog>
  );
}
