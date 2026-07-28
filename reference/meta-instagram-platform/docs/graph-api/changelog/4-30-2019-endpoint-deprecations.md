# April 30th, 2019 — Endpoint Deprecations

The following endpoints will be deprecated on April 30th, 2019, for version 3.3+ of the Graph API and Marketing API. Apps that have used these endpoints in the last 90 days can continue using them with API versions 3.2 and lower until July 30th, 2019. Apps that have not used any of these endpoints in the last 90 days will be unable to use them starting on April 30th, 2019.

## 3D Posts

* `GET /{with-asset-3d-id}`

## Albums

* `DELETE /{album-id}/likes`
* `GET /{album-id}/sharedposts`
* `POST /albums`

## API

* `DELETE /{favorite-request-id}`
* `GET /api_version` (reinstated August 2, 2019)

## Applications

See [Corrections](#corrections).

* `DELETE /{application-id}/roles`
* `GET /{application-id}/achievements`
* `GET /{application-id}/albums`
* `GET /{application-id}/audiences`
* `GET /{application-id}/connections`
* `GET /{application-id}/direct_deals`
* `GET /{application-id}/insights_event_labels`
* `GET /{application-id}/leadgen_integrations`
* `GET /{application-id}/local_service_booking_config`
* `GET /{application-id}/object_types`
* `GET /{application-id}/payments`
* `GET /{application-id}/payments_test_users`
* `GET /{application-context-id}`
* `GET /{app-request-id}/picture`
* `GET /{domain-id}`
* `GET /{domain-id}/feed`
* `POST /{application-id}/achievements`
* `POST /{application-id}/connected_devices`
* `POST /{application-id}/machines`
* `POST /{application-id}/photos`
* `POST /{application-id}/roles`
* `POST /{application-id}/uploads`

## Businesses

See [Corrections](#corrections).

* `GET /{business-id}/adaccountcreationrequests`
* `GET /{business-id}/assigned_ad_accounts`
* `GET /{business-id}/assigned_pages`
* `GET /{business-id}/assigned_product_catalogs`
* `GET /{business-id}/business_persona`
* `GET /{business-id}/businesssettinglogs`
* `GET /{business-id}/catalog_segment_producer_tos`
* `GET /{business-id}/grp_plans`
* `GET /{business-id}/owned_custom_conversions`
* `GET /{business-id}/pages`
* `GET /{business-id}/partner_integrations`
* `GET /{business-id}/upload_event`
* `GET /{business-id}/user_invitations`
* `GET /{business-persona-id}`
* `GET /{business-user-id}/businesssettinglogs`

## Canvases

* `DELETE /{canvas-id}`
* `DELETE /{canvas-button-id}`
* `DELETE /{canvas-carousel-id}`
* `DELETE /{canvas-product-set}`
* `GET /{canvas-dynamic-text-id}`
* `GET /{canvas-lead-form-id}`
* `GET /{canvas-store-locator-id}`
* `GET /{canvas-template-id}` (reinstated March 17, 2021)
* `POST /{canvas-id}/duplicate_canvas`
* `POST /{canvas-id}/preview_notifications`
* `POST /{canvas-button-id}`
* `POST /{canvas-carousel-id}`
* `POST /{canvas-footer-id}`
* `POST /{canvas-header-id}`
* `POST /{canvas-photo-id}`
* `POST /{canvas-product-set-id}`
* `POST /{canvas-text-id}`
* `POST /{canvas-video-id}`

## Comments

* `GET /{comment-id}/picture`

## Events

* `GET /{event-id}/live_videos`
* `POST /{event-id}/attending`
* `POST /{event-id}/comments`
* `POST /{event-id}/videos`

## Facebook Login for Devices

* `GET /{device-id}`

## Groups

* `DELETE /{group-id}/moderators`
* `GET /{group-id}/insights`
* `GET /{group-message-id}/albums`
* `GET /{group-message-id}/sharedposts`
* `POST /{group-id}/docs`
* `POST /{group-id}/moderators`
* `POST /{group-id}/reported_content`

## Instagram

* `GET /{instagram-carousel-id}/instagram_comments`
* `GET /{instagram-media-id}/instagram_usertags`
* `POST /{instagram-user-id}/agencies`

## Live Videos

See [Corrections](#corrections).

* `GET /{live-video-id}/game_shows`
* `GET /{live-video-id}/guest_sessions`

## Marketing API

See [Corrections](#corrections).

* `DELETE /{ad-account-creation-request-id}`
* `DELETE /{adgroup-id}/trackingtag`
* `DELETE /{ads-pixel-id}/shared_agencies`
* `DELETE /{rtb-dynamic-post-id}`
* `GET /custom_audience_third_party_id` (reinstated July 30, 2019)
* `GET /{ad-account-id}/adaccount`
* `GET /{ad-account-id}/adcampaignstats`
* `GET /{ad-account-id}/adlanguage_assets`
* `GET /{ad-account-id}/affectedadsets` (reinstated July 30, 2019)
* `GET /{ad-account-id}/brand_audiences` (reinstated July 30, 2019)
* `GET /{ad-account-id}/business_activities`
* `GET /{ad-account-id}/businesssettinglogs`
* `GET /{ad-account-id}/partner_integrations`
* `GET /{ad-account-id}/partnercategories`
* `GET /{ad-account-id}/partnerdata`
* `GET /{ad-account-id}/partners`
* `GET /{ad-account-id}/referral`
* `GET /{ad-account-id}/stats`
* `GET /{ad-account-id}/timezoneoffsets`
* `GET /{ad-campaign-id}/stats`
* `GET /{ad-campaign-group-id}/stats`
* `GET /{ad-creative-mockup-id}`
* `GET /{adgroup-id}/stats`
* `GET /{custom-conversion-id}/adaccounts`
* `GET /{lead-gen-conditional-questions-group-id}`
* `GET /{lead-gen-context-card-id}` (can be queried via `context_card` field on a [LeadGenData](/docs/graph-api/reference/lead-gen-data/) node as of July 11, 2019)
* `GET /{lead-gen-data-draft-id}`
* `GET /{lead-gen-legal-content-id}` (can be queried via `legal_content` field on a [LeadGenData](/docs/graph-api/reference/lead-gen-data/) node as of May 31, 2019)
* `GET /{offline-conversion-data-set-id}/activities`
* `GET /{partner-request-id}`
* `GET /{product-catalog-id}/bundle_folders`
* `GET /{product-catalog-id}/bundles`
* `GET /{product-catalog-id}/da_event_samples`
* `GET /{product-set-id}/da_checks`
* `GET /{tracking-tag-id}`
* `POST /{adgroup-id}/trackingtag`
* `POST /{ad-account-id}/adcreatives_from_mockups`
* `POST /{ad-account-id}/adlanguage_assets`
* `POST /{ad-account-id}/locationclusters` (reinstated July 30, 2019)
* `POST /{ad-account-id}/mockups`
* `POST /{ad-account-id}/partnerdata`
* `POST /{ad-account-id}/product_recommendations`
* `POST /{custom-conversion-id}/adaccounts`
* `POST /{hotel-id}/hotel_rooms`
* `POST /{lead-gen-data-draft-id}`
* `POST /{offline-conversion-data-set-id}/userpermissions`
* `POST /{saved-audience-id}`

## Messages

* `GET /{thread-id}/feed`
* `GET /{thread-id}/posts`
* `GET /{thread-setting-id}`

## Messenger

* `GET /{messenger-destination-page-welcome-message-id}`

## Offers

See [Corrections](#corrections).

* `GET /{offer-id}/comments`
* `GET /{offer-id}/likes`

## Open Graph

See [Corrections](#corrections).

* `DELETE /{open-graph-action-id}/likes`
* `GET /{open-graph-action-type-id}`
* `GET /{open-graph-context-id}`
* `GET /{open-graph-object-id}/external_edge`
* `GET /{open-graph-object-type-id}`
* `POST /{object-album-id}/comments`
* `POST /{object-album-id}/likes`
* `POST /{open-graph-action-id}`
* `POST /{open-graph-object-id}`
* `POST /{open-graph-object-id}/photos`

## Pages

See [Corrections](#corrections).

* `DELETE /{page-id}/leadgen_whitelisted_users`
* `DELETE /{page-id}/video_lists`
* `DELETE /{page-admin-note-id}`
* `DELETE /{page-label-id}`
* `DELETE /{page-label-id}/users`
* `DELETE /{saved-message-response}`
* `DELETE /{unified-thread-id}`
* `GET /{business-asset-sharing-agreement-id}` (reinstated July 29, 2019)
* `GET /{contact-field-id}/feed`
* `GET /{contact-field-id}/friends`
* `GET /{notification-id}`
* `GET /{page-id}/asset3ds`
* `GET /{page-id}/business_activities`
* `GET /{page-id}/change_proposals`
* `GET /{page-id}/crosspost_pending_approval_pages`
* `GET /{page-id}/expired_posts`
* `GET /{page-id}/expiring_posts`
* `GET /{page-id}/insights_exports`
* `GET /{page-id}/jobs`
* `GET /{page-id}/labels`
* `GET /{page-id}/leadgen_conditional_questions_group`
* `GET /{page-id}/leadgen_context_cards`
* `GET /{page-id}/leadgen_draft_forms`
* `GET /{page-id}/leadgen_legal_content`
* `GET /{page-id}/leadgen_qualifiers`
* `GET /{page-id}/leadgen_whitelisted_users`
* `GET /{page-id}/menus`
* `GET /{page-id}/messenger_ads_page_welcome_messages`
* `GET /{page-id}/notifications`
* `GET /{page-id}/restaurant_orders`
* `GET /{page-id}/saved_filters`
* `GET /{page-id}/saved_message_responses`
* `GET /{page-id}/search_dialogs`
* `GET /{page-id}/seasons`
* `GET /{page-id}/video_broadcasts`
* `GET /{page-id}/videos_you_can_use`
* `GET /{page-id}/workflows`
* `GET /{page-admin-note-id}`
* `GET /{page-change-proposal-id}` (reinstated January 29, 2020)
* `GET /{page-label-id}`
* `GET /{page-label-id}/users`
* `GET /{page-post-id}/to`
* `GET /{page-upcoming-change-id}` (reinstated June 16, 2020)
* `GET /{saved-message-response-id}`
* `POST /{notification-id}`
* `POST /{page-id}/activities`
* `POST /{page-id}/admin_notes`
* `POST /{page-id}/labels`
* `POST /{page-id}/leadgen_conditional_questions_group`
* `POST /{page-id}/leadgen_draft_forms`
* `POST /{page-id}/leadgen_whitelisted_users`
* `POST /{page-id}/menus`
* `POST /{page-id}/messenger_codes`
* `POST /{page-id}/milestones`
* `POST /{page-id}/notifications`
* `POST /{page-id}/saved_message_responses`
* `POST /{page-id}/subscriptions`
* `POST /{page-id}/user_ids`
* `POST /{page-id}/video_lists`
* `POST /{page-change-proposal-id}`
* `POST /{page-label-id}/users`
* `POST /{page-name-id}/admin_notes`
* `POST /{saved-message-response-id}`

## Photos

See [Corrections](#corrections).

* `DELETE /{photo-id}/likes`
* `GET /{photo-id}/sharedposts`
* `GET /{photo-url-id}`
* `GET /picture`
* `POST /photos`
* `POST /{photo-id}/photos`
* `POST /{photo-id}/tags`

## Places

* `GET /places_sample`
* `GET /{current-place-id}`
* `GET /{place-information-id}/photos`
* `GET /{place-information-id}/picture`
* `GET /{place-tag-id}`
* `GET /{place-topic-id}/feed`
* `GET /{place-topic-id}/insights`
* `GET /{place-topic-id}/likes`
* `GET /{place-topic-id}/photos`
* `GET /{place-topic-id}/posts`
* `GET /{place-topic-url-id}`
* `POST /{current-place-id}/feedback`
* `POST /{menu-id}`

## Posts

See [Corrections](#corrections).

* `DELETE /{post-id}/reactions`
* `GET /{post-id}/to`
* `POST /{post-id}/photos`

## Search

See [Corrections](#corrections).

* `GET /search:`
* `GET /search:adassetsupportedlanguages`
* `GET /search:adregion` (reinstated July 30, 2019)
* `GET /search:event`

## Users

See [Corrections](#corrections).

* `DELETE /{user-id}/likes`
* `GET /{device-notification-id}/friends`
* `GET /{friend-list-id}`
* `GET /{friend-list-id}/feed`
* `GET /{friend-list-id}/friends`
* `GET /{friend-list-id}/posts`
* `GET /{life-event-id}/comments`
* `GET /{life-event-id}/feed`
* `GET /{life-event-id}/friends`
* `GET /{life-event-id}/insights`
* `GET /{life-event-id}/likes`
* `GET /{life-event-id}/photos`
* `GET /{status-id}`
* `GET /{status-id}/comments`
* `GET /{status-id}/likes`
* `GET /{user-context-id}`
* `GET /{user-id}/achievements`
* `GET /{user-id}/asset3ds`
* `GET /{user-id}/books.quotes`
* `GET /{user-id}/books.rates`
* `GET /{user-id}/books.reads`
* `GET /{user-id}/business_activities`
* `GET /{user-id}/fitness.bikes`
* `GET /{user-id}/fitness.runs`
* `GET /{user-id}/fitness.walks`
* `GET /{user-id}/games.celebrate`
* `GET /{user-id}/games.plays`
* `GET /{user-id}/home`
* `GET /{user-id}/integrated_plugin_feed`
* `GET /{user-id}/invitable_friends`
* `GET /{user-id}/music.listens`
* `GET /{user-id}/music.playlists`
* `GET /{user-id}/news.publishes`
* `GET /{user-id}/news.reads`
* `GET /{user-id}/objects`
* `GET /{user-id}/og.comments`
* `GET /{user-id}/og.follows`
* `GET /{user-id}/og.posts`
* `GET /{user-id}/og.shares`
* `GET /{user-id}/pages.saves`
* `GET /{user-id}/platformrequests`
* `GET /{user-id}/privacy_options`
* `GET /{user-id}/promotable_events`
* `GET /{user-id}/publish`
* `GET /{user-id}/restaurant.visited`
* `GET /{user-id}/save.saves`
* `GET /{user-id}/statuses`
* `GET /{user-id}/tagged_places`
* `GET /{user-id}/video_broadcasts`
* `GET /{user-id}/video.rates`
* `GET /{user-id}/video.watches`
* `POST /{user-id}/albums`
* `POST /{user-id}/favorite_requests`
* `POST /{user-id}/friends`
* `POST /{user-id}/likes`
* `POST /{user-id}/loggedoutpushsetnonces`
* `POST /{user-id}/objects`
* `POST /{test-user-id}/friends`

## Videos

See [Corrections](#corrections).

* `DELETE /{video-id}/captions`
* `DELETE /{video-id}/likes`
* `DELETE /{video-list-id}/videos`
* `GET /{video-id}/auto_generated_captions`
* `GET /{video-auto-generated-captions-id}`
* `GET /{video-chunked-upload-session-id}/friends`
* `POST /{video-list-id}/videos`

## Corrections

The following endpoints were erroneously listed. They are undergoing further analysis and will not be deprecated at this time.

* `DELETE /{page-call-to-action-id}`
* `DELETE /{user-lead-gen-info-id}`
* `GET /{ad-campaign-group-id}/ad_studies`
* `GET /{ad-campaign-id}/asyncadrequests`
* `GET /{ad-campaign-id}/copies`
* `GET /{application-id}/app_insights`
* `GET /{application-id}/foreign_exchanges`
* `GET /{application-id}/picture`
* `GET /{lead-gen-direct-crm-integration-third-party-app-id}`
* `GET /{live-video-id}/blocked_users`
* `GET /{live-video-id}/crossposted_broadcasts`
* `GET /{live-video-id}/errors`
* `GET /{live-video-input-stream-id}`
* `GET /{native-offer-id}/views`
* `GET /{open-graph-action-id}/likes`
* `GET /{open-graph-object-id}/reactions`
* `GET /{page-call-to-action-id}`
* `GET /{page-id}/call_to_actions`
* `GET /{page-id}/canvas_elements`
* `GET /{page-id}/crosspost_whitelisted_pages`
* `GET /{page-id}/featured_videos_collection`
* `GET /{page-id}/leadgen_integrations`
* `GET /{page-id}/place_topics`
* `GET /{page-id}/product_catalogs`
* `GET /{page-id}/screennames`
* `GET /{page-id}/show_playlists`
* `GET /{page-post-id}/edit_actions`
* `GET /{page-post-id}/sponsor_tags`
* `GET /{page-post-id}/with_tags`
* `GET /{photo-id}/sponsor_tags`
* `GET /{post-id}/edit_actions`
* `GET /{post-id}/with_tags`
* `GET /{rtb-dynamic-post-id}/comments`
* `GET /{rtb-dynamic-post-id}/likes`
* `GET /{single-recommendation-story-id}/reactions`
* `GET /{user-id}/domains`
* `GET /{user-id}/payments`
* `GET /{user-id}/rich_media_documents`
* `GET /{user-id}/session_keys`
* `GET /{video-id}/sponsor_tags`
* `GET /{video-id}/tags`
* `GET /ads_geo_coding`
* `GET /search:placetopic`
* `GET /search:targetingoptionstatus`
* `POST /{ad-campaign-group-id}/product_recommendations`
* `POST /{ad-campaign-id}/product_recommendations`
* `POST /{application-id}/leadgen_integrations`
* `POST /{live-video-id}/input_streams`
* `POST /{page-call-to-action-id}`
* `POST /{page-name-id}/broadcast_messages`
* `POST /{page-name-id}/message_creatives`
* `POST /{page-name-id}/messages`
* `POST /{page-name-id}/messenger_codes`
* `POST /{page-name-id}/messenger_profile`
* `POST /{native-offer-id}/codes`
* `POST /{page-name-id}/thread_settings`
* `POST /{user-id}/ad_studies`
