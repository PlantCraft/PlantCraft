import { describe, expect, it } from "vitest";
import { ssoStartUrl } from "./directoryApi";
import { serverMoved } from "./CorporateLogin";

describe("ssoStartUrl", () => {
  it("comes back to a path on this site only", () => {
    expect(ssoStartUrl("/cpm/loops?area=north")).toBe("/api/sso/oidc/start?next=%2Fcpm%2Floops%3Farea%3Dnorth");
    expect(ssoStartUrl(null)).toBe("/api/sso/oidc/start");
    expect(ssoStartUrl("//evil.test")).toBe("/api/sso/oidc/start");
    expect(ssoStartUrl("https://evil.test")).toBe("/api/sso/oidc/start");
  });
});

describe("serverMoved", () => {
  it("notices a new address or account, not spacing or a trailing slash", () => {
    expect(serverMoved(["ldaps://dc1", "cn=svc"], ["ldaps://dc1 ", "cn=svc"])).toBe(false);
    expect(serverMoved(["https://sso/realms/a", "pc"], ["https://sso/realms/a/", "pc"])).toBe(false);
    expect(serverMoved(["ldaps://dc1", "cn=svc"], ["ldaps://evil", "cn=svc"])).toBe(true);
    expect(serverMoved(["ldaps://dc1", "cn=svc"], ["ldaps://dc1", "cn=other"])).toBe(true);
  });
});
