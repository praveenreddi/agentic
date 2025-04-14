import { ApplicationConfig, importProvidersFrom } from "@angular/core";
import { provideRouter } from "@angular/router";
import { routes } from "./app.routes";
import {
  provideHttpClient,
  withInterceptors,
  HttpRequest,
  HttpHandlerFn,
  HttpEvent,
} from "@angular/common/http";
import { environment } from "../environments/environment";
import { Observable, from, of } from "rxjs";
import { switchMap, catchError, shareReplay } from "rxjs/operators";

// Import MSAL modules and configurations
import {
  MsalModule,
  MsalGuard,
  MSAL_INSTANCE,
  MsalInterceptorConfiguration,
  MsalService,
} from "@azure/msal-angular";
import {
  PublicClientApplication,
  InteractionType,
  IPublicClientApplication,
  AuthenticationResult,
} from "@azure/msal-browser";
import { msalConfig, loginRequest } from "./auth-config";

// Factory function to create the MSAL instance
export function MSALInstanceFactory(): IPublicClientApplication {
  console.log("Creating MSAL instance in app.config.ts");
  return new PublicClientApplication(msalConfig);
}

// Factory function for the interceptor configuration
export function MSALInterceptorConfigFactory(): MsalInterceptorConfiguration {
  console.log("Creating MSAL interceptor config");
  console.log("API URL:", environment.apiUrl);
  console.log("API Scope:", environment.apiScope);

  const protectedResourceMap = new Map<string, Array<string>>();
  // Set the User.Read scope for all API calls
  protectedResourceMap.set(environment.apiUrl, ["User.Read"]);

  return {
    interactionType: InteractionType.Redirect,
    protectedResourceMap,
  };
}

// Log if SSO is enabled
console.log("SSO Enabled:", environment.enableSSO);

// Create MSAL instance at the module level
const msalInstance = new PublicClientApplication(msalConfig);

// Initialize the MSAL instance
msalInstance
  .initialize()
  .then(() => {
    console.log("MSAL instance initialized successfully");
  })
  .catch((error) => {
    console.error("Error initializing MSAL instance:", error);
  });

// Token cache to avoid requesting a new token for every API call
let cachedTokenObservable: Observable<AuthenticationResult> | null = null;
let tokenExpiresAt: number = 0;

// Function to get a token, either from cache or by acquiring a new one
function getTokenObservable(): Observable<AuthenticationResult> {
  const now = Date.now();

  // If we have a cached token that isn't expired (with 5 min buffer), return it
  if (cachedTokenObservable && tokenExpiresAt > now + 300000) {
    console.log("Using cached token");
    return cachedTokenObservable;
  }

  console.log("Token expired or not cached, acquiring new token");
  const accounts = msalInstance.getAllAccounts();

  if (accounts.length === 0) {
    console.error("No accounts found");
    return of({} as AuthenticationResult);
  }

  const account = accounts[0];
  console.log("Acquiring token for account:", account.username);

  // Create a new token request and cache it - using User.Read scope which is always available
  cachedTokenObservable = from(
    msalInstance.acquireTokenSilent({
      account: account,
      scopes: ["User.Read"],
    }),
  ).pipe(
    shareReplay(1),
    catchError((error) => {
      console.error("Token acquisition failed:", error);
      // Clear cache on error
      cachedTokenObservable = null;
      tokenExpiresAt = 0;
      return of({} as AuthenticationResult);
    }),
  );

  // Update expiration time (tokens typically last 1 hour)
  tokenExpiresAt = now + 3600000; // 1 hour

  return cachedTokenObservable;
}

export const appConfig: ApplicationConfig = {
  providers: [
    provideRouter(routes),

    // Always provide HttpClient with appropriate interceptors
    provideHttpClient(
      withInterceptors([
        // Add a simple interceptor that adds the token manually
        (
          req: HttpRequest<unknown>,
          next: HttpHandlerFn,
        ): Observable<HttpEvent<unknown>> => {
          // Only add tokens for API calls
          if (req.url.startsWith(environment.apiUrl) && environment.enableSSO) {
            // Get token from cache or acquire a new one
            return getTokenObservable().pipe(
              switchMap((response) => {
                if (response && response.accessToken) {
                  console.log("Adding token to request");
                  // Clone the request and add the authorization header
                  const authReq = req.clone({
                    setHeaders: {
                      Authorization: `Bearer ${response.accessToken}`,
                    },
                  });

                  return next(authReq);
                } else {
                  // Proceed without token if we couldn't get one
                  console.warn("No valid token available");
                  return next(req);
                }
              }),
            );
          }

          // For non-API calls
          return next(req);
        },
      ]),
    ),

    // Conditionally add MSAL providers if SSO is enabled
    ...(environment.enableSSO
      ? [
          // MSAL providers for authentication (not for API calls)
          { provide: MSAL_INSTANCE, useFactory: MSALInstanceFactory },
          MsalService,
          MsalGuard,
          importProvidersFrom(
            MsalModule.forRoot(
              MSALInstanceFactory(),
              {
                interactionType: InteractionType.Redirect,
                authRequest: loginRequest,
                loginFailedRoute: "/chat",
              },
              MSALInterceptorConfigFactory(),
            ),
          ),
        ]
      : []),
  ],
};
