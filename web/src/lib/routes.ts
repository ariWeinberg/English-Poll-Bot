import type { Route } from "../types";

function normalizePathname(pathname: string) {
  if (!pathname || pathname === "/") return "/";
  return pathname.replace(/\/+$/, "") || "/";
}

export function parseRoute(pathname: string): Route {
  const path = normalizePathname(pathname);
  if (path === "/register") return { name: "register" };
  if (path === "/dashboard" || path === "/") return { name: "dashboard" };
  if (path === "/learners") return { name: "learners" };
  if (path === "/chats") return { name: "chats" };
  if (path === "/texts") return { name: "texts" };
  if (path === "/rules") return { name: "rules" };
  if (path === "/polls") return { name: "polls" };
  if (path === "/doc") return { name: "doc" };
  if (path === "/settings") return { name: "settings" };
  const learnerMatch = path.match(/^\/learners\/(.+)$/);
  if (learnerMatch) return { name: "learner-detail", voterWid: decodeURIComponent(learnerMatch[1]) };
  const textMatch = path.match(/^\/texts\/(\d+)$/);
  if (textMatch) return { name: "text-detail", id: Number(textMatch[1]) };
  const pollMatch = path.match(/^\/polls\/(\d+)$/);
  if (pollMatch) return { name: "poll-detail", id: Number(pollMatch[1]) };
  return { name: "login" };
}

export function routeHref(route: Route): string {
  switch (route.name) {
    case "register":
      return "/register";
    case "dashboard":
      return "/dashboard";
    case "learners":
      return "/learners";
    case "learner-detail":
      return `/learners/${encodeURIComponent(route.voterWid)}`;
    case "chats":
      return "/chats";
    case "texts":
      return "/texts";
    case "text-detail":
      return `/texts/${route.id}`;
    case "rules":
      return "/rules";
    case "polls":
      return "/polls";
    case "poll-detail":
      return `/polls/${route.id}`;
    case "doc":
      return "/doc";
    case "settings":
      return "/settings";
    default:
      return "/login";
  }
}

export function navigateTo(route: Route, replace = false) {
  const href = routeHref(route);
  if (replace) window.history.replaceState({}, "", href);
  else window.history.pushState({}, "", href);
  window.dispatchEvent(new PopStateEvent("popstate"));
}
