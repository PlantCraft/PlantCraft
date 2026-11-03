# Starter model: a small credit of PlantCraft's own model (planned, off)

**Status: off.** Nothing is spent and nothing calls plantcraft.io. The switch exists so the
feature can be turned on later without a redesign.

## Why

The setup guide's first step is a language model: before it, the robot cannot talk. A person who
just installed PlantCraft may have no API key at hand. A small credit of PlantCraft's own model,
enough to finish the setup and the first missions, removes that wall.

## How it works (when on)

1. On the model step the guide offers **Use PlantCraft's model** next to *Use my own model*.
2. The installation asks the hosted side for a credit token. The token is PlantCraft's, one per
   installation, and can be revoked. **The provider's API key never leaves the hosted side.**
3. The installation saves it as an OpenAI-compatible model whose endpoint is the hosted proxy.
4. The proxy counts what each token spends and answers *credit used up* at the limit. The guide
   shows what is left ("R$ 1,80 of R$ 2,50 left") and, at the end, how to add the person's own
   model. Buying more credit is a later step.

## Hosted side

It lives in `site/sitechat` on the VPS, which already holds the site chat's model key and its
per-address and daily limits (`site/sitechat/guard.py`). It adds: token issue (one per
installation id, per address per day), a spend counter per token, and a monthly cap for all
tokens that turns the credit off for everyone once reached.

## Settings

| Where | Setting | Default | Meaning |
| --- | --- | --- | --- |
| Installation | `PLANTCRAFT_STARTER_MODEL` | `off` | `on` shows the offer on the model step |
| Installation | `PLANTCRAFT_STARTER_MODEL_URL` | `https://plantcraft.io/api/starter-model` | The hosted proxy |
| Hosted | `STARTER_CREDIT` | `0` | Credit per installation (amount) |
| Hosted | `STARTER_MONTHLY_CAP` | `0` | Spend for all installations in a month; `0` is off |
| Hosted | `STARTER_CURRENCY` | `BRL` | Currency the amounts and the guide use |

Turning it on is a spending decision: it needs the owner's written OK and a provider key with
its own spend limit.
