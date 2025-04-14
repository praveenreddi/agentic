import { Configuration, LogLevel } from "@azure/msal-browser";
import { environment } from "../environments/environment";

// MSAL configuration
export const msalConfig: Configuration = {
  auth: {
    clientId: environment.auth.clientId,
    authority: environment.auth.authority,
    redirectUri: window.location.origin,
  },
  cache: {
    cacheLocation: "localStorage",
    storeAuthStateInCookie: true,
  },
  system: {
    loggerOptions: {
      loggerCallback: (level, message, containsPii) => {
        if (containsPii) {
          return;
        }
        switch (level) {
          case LogLevel.Error:
            console.error(message);
            break;
          case LogLevel.Info:
            console.info(message);
            break;
          case LogLevel.Verbose:
            console.debug(message);
            break;
          case LogLevel.Warning:
            console.warn(message);
            break;
          default:
            break;
        }
      },
      piiLoggingEnabled: false,
    },
    windowHashTimeout: 60000,
    iframeHashTimeout: 6000,
    loadFrameTimeout: 0,
  },
};

// Add here scopes for token request
export const loginRequest = {
  scopes: ["User.Read"],
};

// Add here the endpoints and scopes for the web API you would like to use.
export const protectedResources = {
  api: {
    endpoint: environment.apiUrl,
    scopes: [environment.apiScope],
  },
};
