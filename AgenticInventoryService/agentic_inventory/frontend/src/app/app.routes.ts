import { Routes } from "@angular/router";
import { ChatPageComponent } from "./chat-page/chat-page.component";
import { environment } from "../environments/environment";
import { MsalGuard } from "@azure/msal-angular";
import { MsalRedirectComponent } from "@azure/msal-angular";

export const routes: Routes = [
  // Default route redirects to chat
  { path: "", redirectTo: "/chat", pathMatch: "full" },

  // Main chat component with conditional guard based on SSO setting
  {
    path: "chat",
    component: ChatPageComponent,
    canActivate: environment.enableSSO ? [MsalGuard] : [],
  },

  // This is needed for handling redirects after login
  { path: "auth", component: MsalRedirectComponent },
];
