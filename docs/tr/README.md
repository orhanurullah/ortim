# Ortim — Türkçe giriş

> Bu, kısa bir giriş kapısıdır. **Tüm ayrıntı** kapsamlı kullanım rehberindedir:
> [`kullanim-rehberi.md`](./kullanim-rehberi.md) — kurulumdan hata kurtarmaya, her
> adım ve her durum.
>
> Kanonik (en güncel) kaynak İngilizce [`../../README.md`](../../README.md)'dir;
> bu Türkçe yüzey ondan biraz geride kalabilir.

Ortim, tek paragraflık bir brief'i → çalışan, gözden geçirilmiş, **denetim izli** koda
dönüştüren disiplinli, çok-ajanlı bir AI yazılım fabrikasıdır. Felsefe: *markdown bilgiyi
söyler, runtime kuralı zorlar.* LLM "atlamak" istese bile deterministik state machine, iki
zorunlu insan kapısı (G1=PRD, G2=RFC), kural-tabanlı tier scorer ve DAG validator engeller.

## Kurulum

```bash
pip install ortim          # Python ≥ 3.11
ortim config init          # sağlayıcı (DeepSeek / Anthropic / yerel Ollama) + anahtar
ortim doctor               # ortam sağlık kontrolü
```

`.env` şart değil; `ortim config init` `~/.ortim/config.toml`'a yazar. API anahtarı olmadan
denemek için: `ortim demo` (veya tamamen yerel: `ortim demo --provider ollama`).

## Nereden devam etmeli

| İhtiyaç | Doküman |
|---|---|
| **Her şey** — komutlar, akış, gate'ler, kurtarma, maliyet | [`kullanim-rehberi.md`](./kullanim-rehberi.md) |
| Adım-adım ilk proje (~15 dk) | [`tutorial/getting-started.md`](./tutorial/getting-started.md) |
| Bir görev takıldı / gate tetiklendi → kurtarma | [`runbook/failure-recovery.md`](./runbook/failure-recovery.md) |
| Mimari spec (TR/EN karışık) | [`../../Ortim_Architecture.md`](../../Ortim_Architecture.md) |
| İngilizce kanonik README | [`../../README.md`](../../README.md) |

## En kısa akış

```bash
mkdir ~/dev/proje && cd ~/dev/proje
ortim init "<brief>"        # .ortim/ oluşur (brownfield otomatik tespit)
ortim run                   # Babel + Analyst → PRD taslağı
ortim scope --lock          # MVP kapsamını kilitle → G1
ortim advance prd_approved  # G1 onayı
ortim run                   # Architect → RFC
ortim advance rfc_approved  # G2 onayı
ortim run                   # Orchestrator → görev DAG'ı
ortim run-all --phase 1     # Worker + Reviewer (MVP görevleri)
```

Her komut bulunduğun dizindeki `.ortim/`'i keşfeder (cwd-aware). Ayrıntılı seçenekler,
tüm state'ler ve hata durumları için → [`kullanim-rehberi.md`](./kullanim-rehberi.md).

## Lisans

- **Core**: [FSL-1.1-Apache-2.0](../../LICENSE) — 2 yıl Functional Source License
  (non-compete), sonra otomatik Apache-2.0.
- **Enterprise** (`enterprise/`): [Commercial](../../LICENSE.commercial) — multi-tenant
  orchestrator, SSO, audit retention, SLA. Şu an iskelet.

Sorun bildirimi: [github.com/orhanurullah/ortim/issues](https://github.com/orhanurullah/ortim/issues)
