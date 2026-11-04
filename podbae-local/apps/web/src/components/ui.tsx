// shadcn/ui-style components on real Radix primitives.
import * as AccordionPrimitive from '@radix-ui/react-accordion';
import * as DialogPrimitive from '@radix-ui/react-dialog';
import * as LabelPrimitive from '@radix-ui/react-label';
import { Slot } from '@radix-ui/react-slot';
import * as SwitchPrimitive from '@radix-ui/react-switch';
import * as TabsPrimitive from '@radix-ui/react-tabs';
import { cva, type VariantProps } from 'class-variance-authority';
import { ChevronDown, X } from 'lucide-react';
import {
  forwardRef, useEffect, useState,
  type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode, type TextareaHTMLAttributes,
} from 'react';
import { cn } from '../lib/utils';

// ---------- Button ----------
const buttonVariants = cva(
  'inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-[10px] text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50',
  {
    variants: {
      variant: {
        default: 'bg-primary text-primary-foreground hover:bg-primary/90',
        outline: 'border border-input bg-card hover:bg-secondary',
        secondary: 'bg-secondary text-secondary-foreground hover:bg-secondary/80',
        ghost: 'hover:bg-secondary',
        destructive: 'bg-destructive text-destructive-foreground hover:bg-destructive/90',
        link: 'text-primary underline-offset-4 hover:underline',
      },
      size: { sm: 'h-9 px-3', md: 'h-10 px-4 py-2', lg: 'h-11 px-8', icon: 'h-10 w-10' },
    },
    defaultVariants: { variant: 'default', size: 'md' },
  },
);
export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof buttonVariants> {
  asChild?: boolean;
}
export const Button = forwardRef<HTMLButtonElement, ButtonProps>(({ className, variant, size, asChild, ...p }, ref) => {
  const Comp = asChild ? Slot : 'button';
  return <Comp ref={ref} className={cn(buttonVariants({ variant, size }), className)} {...p} />;
});
Button.displayName = 'Button';

// ---------- form ----------
const fieldCls = 'flex w-full rounded-md border border-input bg-card px-3 py-2 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50';
export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(({ className, ...p }, ref) => (
  <input ref={ref} className={cn(fieldCls, 'h-10', className)} {...p} />
));
Input.displayName = 'Input';
export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(({ className, ...p }, ref) => (
  <textarea ref={ref} rows={3} className={cn(fieldCls, 'min-h-[80px]', className)} {...p} />
));
Textarea.displayName = 'Textarea';
export function Select({ className, ...p }: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return <select className={cn(fieldCls, 'h-10', className)} {...p} />;
}
export const Label = forwardRef<HTMLLabelElement, React.ComponentPropsWithoutRef<typeof LabelPrimitive.Root>>(({ className, ...p }, ref) => (
  <LabelPrimitive.Root ref={ref} className={cn('text-sm font-medium leading-none', className)} {...p} />
));
Label.displayName = 'Label';
export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <div className="space-y-1.5">
      <Label>{label} {hint && <span className="font-normal text-muted-foreground">{hint}</span>}</Label>
      {children}
    </div>
  );
}
export const Switch = forwardRef<HTMLButtonElement, React.ComponentPropsWithoutRef<typeof SwitchPrimitive.Root>>(({ className, ...p }, ref) => (
  <SwitchPrimitive.Root ref={ref} className={cn('peer inline-flex h-6 w-11 shrink-0 cursor-pointer items-center rounded-full border-2 border-transparent bg-input transition-colors data-[state=checked]:bg-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring', className)} {...p}>
    <SwitchPrimitive.Thumb className="pointer-events-none block h-5 w-5 rounded-full bg-white shadow transition-transform data-[state=checked]:translate-x-5 data-[state=unchecked]:translate-x-0" />
  </SwitchPrimitive.Root>
));
Switch.displayName = 'Switch';

export function ChipSelect({ options, value, onChange }: { options: readonly string[]; value: string[]; onChange: (v: string[]) => void }) {
  return (
    <div className="flex flex-wrap gap-2">
      {options.map((o) => {
        const on = value.includes(o);
        return (
          <button type="button" key={o} aria-pressed={on} onClick={() => onChange(on ? value.filter((x) => x !== o) : [...value, o])}
            className={cn('rounded-full border px-3 py-1 text-xs font-medium transition', on ? 'border-primary bg-primary text-primary-foreground' : 'border-input bg-card hover:bg-secondary')}>
            {o}
          </button>
        );
      })}
    </div>
  );
}

// ---------- layout bits ----------
export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={cn('rounded-xl border bg-card p-5 text-card-foreground', className)}>{children}</div>;
}
export function Badge({ children, tone = 'default', className }: { children: ReactNode; tone?: 'default' | 'pink' | 'green' | 'gray'; className?: string }) {
  return (
    <span className={cn('inline-block rounded-full px-2.5 py-0.5 text-xs font-medium',
      tone === 'default' && 'bg-secondary text-secondary-foreground', tone === 'pink' && 'bg-primary/15 text-primary',
      tone === 'green' && 'bg-green-500/15 text-green-600', tone === 'gray' && 'bg-muted text-muted-foreground', className)}>
      {children}
    </span>
  );
}
export function Spinner() {
  return <div className="py-10 text-center text-sm text-muted-foreground">Loading…</div>;
}
export function Empty({ children }: { children: ReactNode }) {
  return <div className="rounded-xl border border-dashed p-8 text-center text-sm text-muted-foreground">{children}</div>;
}

// ---------- Tabs (Radix) ----------
export function Tabs({ tabs, value, onChange }: { tabs: { id: string; label: string }[]; value: string; onChange: (id: string) => void }) {
  return (
    <TabsPrimitive.Root value={value} onValueChange={onChange}>
      <TabsPrimitive.List className="inline-flex flex-wrap items-center gap-1 rounded-lg bg-card p-1 border">
        {tabs.map((t) => (
          <TabsPrimitive.Trigger key={t.id} value={t.id}
            className="rounded-md px-3 py-1.5 text-sm font-medium text-muted-foreground transition data-[state=active]:bg-primary data-[state=active]:text-primary-foreground">
            {t.label}
          </TabsPrimitive.Trigger>
        ))}
      </TabsPrimitive.List>
    </TabsPrimitive.Root>
  );
}

// ---------- Accordion (Radix) ----------
export function Accordion({ items }: { items: { q: string; a: ReactNode }[] }) {
  return (
    <AccordionPrimitive.Root type="single" collapsible className="space-y-3">
      {items.map((it, i) => (
        <AccordionPrimitive.Item key={it.q} value={`i${i}`} className="rounded-xl border bg-card px-5">
          <AccordionPrimitive.Header>
            <AccordionPrimitive.Trigger className="flex w-full items-center justify-between py-4 text-left font-semibold [&[data-state=open]>svg]:rotate-180">
              {it.q} <ChevronDown className="h-4 w-4 shrink-0 transition-transform" />
            </AccordionPrimitive.Trigger>
          </AccordionPrimitive.Header>
          <AccordionPrimitive.Content className="pb-4 text-sm text-muted-foreground">{it.a}</AccordionPrimitive.Content>
        </AccordionPrimitive.Item>
      ))}
    </AccordionPrimitive.Root>
  );
}

// ---------- Dialog (Radix) ----------
export function Dialog({ open, onOpenChange, title, children }: { open: boolean; onOpenChange: (o: boolean) => void; title: string; children: ReactNode }) {
  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-black/50" />
        <DialogPrimitive.Content className="fixed left-1/2 top-1/2 z-50 w-[92vw] max-w-lg -translate-x-1/2 -translate-y-1/2 rounded-xl border bg-card p-6 shadow-lg">
          <DialogPrimitive.Title className="mb-3 text-lg font-bold">{title}</DialogPrimitive.Title>
          <DialogPrimitive.Description className="sr-only">{title}</DialogPrimitive.Description>
          {children}
          <DialogPrimitive.Close className="absolute right-4 top-4 opacity-60 hover:opacity-100" aria-label="Close"><X className="h-4 w-4" /></DialogPrimitive.Close>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}

// ---------- toast ----------
type T = { id: number; msg: string };
const listeners = new Set<(t: T) => void>();
export function toast(msg: string) {
  listeners.forEach((l) => l({ id: Date.now() + Math.random(), msg }));
}
export function ToastHost() {
  const [items, setItems] = useState<T[]>([]);
  useEffect(() => {
    const l = (t: T) => {
      setItems((x) => [...x, t]);
      setTimeout(() => setItems((x) => x.filter((y) => y.id !== t.id)), 3500);
    };
    listeners.add(l);
    return () => void listeners.delete(l);
  }, []);
  return (
    <div className="fixed bottom-4 right-4 z-[60] space-y-2" role="status">
      {items.map((t) => (
        <div key={t.id} className="rounded-lg bg-foreground px-4 py-3 text-sm font-medium text-background shadow-lg">{t.msg}</div>
      ))}
    </div>
  );
}
