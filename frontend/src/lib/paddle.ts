import { initializePaddle, type Paddle, type PaddleEventData } from "@paddle/paddle-js";

const token = process.env.NEXT_PUBLIC_PADDLE_CLIENT_TOKEN;

let paddle: Promise<Paddle | undefined> | null = null;
let onEvent: ((e: PaddleEventData) => void) | null = null;

/** Paddle.js, loaded once. Events go to whichever handler the current page registered. */
export function loadPaddle(environment: "sandbox" | "production"): Promise<Paddle | undefined> {
  if (!token) {
    return Promise.reject(
      new Error("Paddle isn't configured: set NEXT_PUBLIC_PADDLE_CLIENT_TOKEN in .env.local."),
    );
  }
  paddle ??= initializePaddle({
    environment,
    token,
    eventCallback: (e) => onEvent?.(e),
  });
  return paddle;
}

/** Open Paddle Checkout and resolve with the transaction id once payment completes
 * (or null if the buyer closes the checkout). */
export async function openCheckout(opts: {
  environment: "sandbox" | "production";
  priceId: string;
  email: string | null;
  customData: Record<string, string>;
}): Promise<string | null> {
  const p = await loadPaddle(opts.environment);
  if (!p) throw new Error("Paddle checkout couldn't load. Check your connection and try again.");
  return new Promise((resolve) => {
    onEvent = (e) => {
      if (e.name === "checkout.completed") {
        onEvent = null;
        resolve(e.data?.transaction_id ?? null);
        p.Checkout.close();
      } else if (e.name === "checkout.closed") {
        onEvent = null;
        resolve(null);
      }
    };
    p.Checkout.open({
      items: [{ priceId: opts.priceId, quantity: 1 }],
      customer: opts.email ? { email: opts.email } : undefined,
      customData: opts.customData,
      settings: { displayMode: "overlay", theme: "dark", allowLogout: false },
    });
  });
}
