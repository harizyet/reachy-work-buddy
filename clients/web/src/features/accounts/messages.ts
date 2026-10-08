/** The hub reports problems as short codes; these are the sentences shown for them. */
export const ACCOUNT_MESSAGES: Record<string, string> = {
  setup_required: 'Complete the one-time connection setup below first.',
  authorization_cancelled: 'Google sign-in was cancelled. You can try again whenever you are ready.',
  permissions_not_granted: 'Google did not grant all the read permissions needed. Reconnect and allow the permissions for this feature.',
  invalid_or_expired_authorization: 'This sign-in link has expired or was already used. Select Connect to start again.',
  different_google_account_disconnect_first: 'Both features must use the same Google account. Disconnect first to choose a different account.',
  offline_access_missing_reconnect: 'Google did not provide ongoing access. Select Reconnect and approve access again.',
  stale: 'The last check is out of date. Select Test connection to check Google access.',
  reconnect_required: 'Google access has expired or was revoked. Select Reconnect.',
  temporarily_unavailable: 'Google is temporarily unavailable. Please try again shortly.',
  permission_denied: 'Google refused this read. Check the enabled APIs and reconnect with the requested permissions.',
  result_limit_exceeded: 'Too many results. Narrow your search or select fewer calendars.',
  select_calendars: 'Choose at least one calendar and save your choices.',
  selected_calendar_unavailable: 'A selected calendar is no longer available. Update your calendar choices.',
  disconnect_required_for_client_change: 'Select the disconnect checkbox before replacing an existing connection.',
  credential_unavailable: 'The saved connection cannot be opened. Ask the person who manages this Reachy installation to check its credential key.',
  not_connected: 'Connect this feature first.',
  unknown_calendar: 'Choose calendars from the current list and save again.',
  invalid_provider_response: 'Google returned an unexpected response. Please try Test connection.',
  provider_request_failed: 'Google could not complete this request. Please try again.',
  response_too_large: 'This item is too large to preview here. Open it in Google instead.',
  invalid_date_range: 'Choose a time range of at most 31 days.',
  invalid_message_id: 'Choose a message from the current mail list.',
  invalid_event: 'A calendar event could not be read. Try Test connection.',
  invalid_pagination: 'Google returned an unexpected page of results. Please try again.',
};

export const sayAccount = (value: string) => ACCOUNT_MESSAGES[value] ?? value;
export const shellQuote = (value: string) => "'" + value.replace(/'/g, "'\\''") + "'";
