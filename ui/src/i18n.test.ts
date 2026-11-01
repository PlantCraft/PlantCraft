// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";
import { fillText } from "./files";
import { configureUi, createI18n, LANGUAGE_COOKIE, LANGUAGE_STORAGE_KEY, supportedLanguage, t, translationsOn, TRANSLATIONS_COOKIE, uiLocale } from "./i18n";
import uiPtBR from "./locales/pt-BR.json";

function clearCookies() {
  for (const name of [LANGUAGE_COOKIE, TRANSLATIONS_COOKIE]) document.cookie = `${name}=; path=/; max-age=0`;
}

afterEach(() => {
  clearCookies();
  window.localStorage.clear();
  configureUi({ t: fillText, locale: "en-US", translations: false });
});

const APP = { "pt-BR": { "Rules": "Regras", "Rule {name}": "Regra {name}" } };

describe("createI18n", () => {
  it("draws English while the server keeps translations off, whatever was chosen", () => {
    window.localStorage.setItem(LANGUAGE_STORAGE_KEY, "pt-BR");
    const i18n = createI18n(APP);
    expect(i18n.language).toBe("en");
    expect(i18n.languages.map((item) => item.code)).toEqual(["en"]);
    expect(i18n.t("Rule {name}", { name: "R1" })).toBe("Rule R1");
    expect(translationsOn()).toBe(false);
    expect(document.cookie).toContain(`${LANGUAGE_COOKIE}=en`);
  });

  it("translates the app's text and the shared components' once the server turns them on", () => {
    document.cookie = `${TRANSLATIONS_COOKIE}=1; path=/`;
    window.localStorage.setItem(LANGUAGE_STORAGE_KEY, "pt-BR");
    const i18n = createI18n(APP);
    expect(i18n.language).toBe("pt-BR");
    expect(i18n.locale).toBe("pt-BR");
    expect(i18n.t("Rule {name}", { name: "R1" })).toBe("Regra R1");
    expect(i18n.t("Not translated yet")).toBe("Not translated yet");
    // The shared components use the same translator, with the package's own catalog under it.
    const [english, portuguese] = Object.entries(uiPtBR as Record<string, string>)[0];
    expect(t(english)).toBe(fillText(portuguese));
    expect(uiLocale()).toBe("pt-BR");
    expect(i18n.languages.map((item) => item.code)).toEqual(["en", "pt-BR", "es"]);
    expect(document.documentElement.lang).toBe("pt-BR");
  });

  it("takes the suite's cookie when this browser stored no choice", () => {
    document.cookie = `${TRANSLATIONS_COOKIE}=1; path=/`;
    document.cookie = `${LANGUAGE_COOKIE}=pt-BR; path=/`;
    expect(createI18n(APP).language).toBe("pt-BR");
  });
});

describe("supportedLanguage", () => {
  it("knows the suite's languages by their tag or base", () => {
    expect(supportedLanguage("pt")).toBe("pt-BR");
    expect(supportedLanguage("en-GB")).toBe("en");
    expect(supportedLanguage("de")).toBeNull();
    expect(supportedLanguage("")).toBeNull();
  });
});

describe("the shared components' catalog", () => {
  it("keeps every {field} of the English text", () => {
    const fields = (text: string) => (text.match(/\{\w*\}/g) ?? []).sort().join();
    for (const [english, portuguese] of Object.entries(uiPtBR as Record<string, string>)) expect(fields(portuguese), english).toBe(fields(english));
  });
});
