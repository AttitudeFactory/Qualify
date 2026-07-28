Graph API Version

[v25.0](#)

# User (`user`)

Full list of user profile fields that you can subscribe to.

## `about`

Describes changes to the About You section of the user's profile.

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |
| `value`  string | The new value |

## `birthday`

Field 'birthday' of Topic 'user'

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |
| `value`  string | Value |

## `books`

Describes changes to the Books section of the user's profile.

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |
| `value`  object | Contents of the update |
| `page`  numeric string | Page that corresponds with the update |
| `verb`  enum {add, block, edit, edited, delete, follow, hide, mute, remove, unblock, unhide, update} | Type of operation |

## `email`

Describes changes to the Email section of the user's profile.

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |
| `value`  string | The new email address |

## `fbe_install`

This node is used to notify the User topic with FBE Install data like the pixel ID and instagram ID.

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |
| `value`  object | This describes the user's FBE install data such as pixel, business id, catalog, and ad account id. |
| `ad_account_id`  string | ad\_account\_id the user selected during onboarding |
| `business_manager_id`  string | Business Manager ID the user selected during onboarding |
| `business_id`  string | business\_id the user selected during onboarding |
| `catalog_id`  string | catalog\_id the user created or selected during onboarding |
| `commerce_merchant_settings_id`  string | Commerce Merchant Settings ID (CMS) the user selected during onboarding |
| `fbe_event`  enum | fbe\_event shares details regarding why the webhook is firing |
| `flow`  enum | flow shares the onboarding flow the merchant went through via FBE |
| `profiles`  list<numeric string> | profiles (list of profiles such as IG profile or Page Profile) |
| `pages`  list<numeric string> | Facebook Business Pages the user selected during onboarding |
| `instagram_profiles`  list<numeric string> | Instagram Business Profiles the user selected during onboarding |
| `install_time`  integer | install\_time of FBE install |
| `pixel_id`  string | pixel\_id the user selected during onboarding |
| `access_token`  string | access\_token for user who installed FBE |
| `onsite_eligible`  bool | checks whether business is onsite\_eligible |
| `token_type`  enum | Token type of access token |
| `installed_features`  [list<FBEBusinessFbeInstalledFeatures>](/docs/graph-api/reference/fbe-business-fbe-installed-features/) | list containing individual feature information |
| `feature_instance_id`  string | ID of the installed FBE feature |
| `feature_name`  string | Unique name given to identify the FBE feature |
| `feature_type`  string | FBE feature type (e.g. Page CTA) |
| `connected_assets`  FBEBusinessFbeInstalledFeatureConnectedAssets | connected\_assets |
| `ad_account_id`  string | The ad account ID of the FBE install |
| `business_manager_id`  string | The Business Manager ID of FBE Install |
| `catalog_id`  string | The catalog ID of the FBE install |
| `commerce_merchant_settings_id`  string | The Commerce Merchant Settings ID associated with the Page of the FBE Install |
| `ig_profile_id`  string | The Instagram Business Profile ID of FBE Install |
| `page_id`  string | The Facebook Page ID of FBE Install |
| `pixel_id`  string | The Pixel ID of FBE Install |
| `additional_info`  FBEBusinessFbeAdditionalInfo | additional\_info |
| `onsite_eligible`  bool | whether a feature is onsite eligible, for BigCommerce use only |
| `pixel_is_consolidated_container`  bool | whether the associated pixel has a consolidated container |
| `partner_integration_id`  string | partner\_integration\_id |
| `installed_intents`  list<KeyValue:enum,list<FBEBusinessFbeInstalledFeatures>> | installed intents |
| `key`  string | Key of the pair |
| `value`  string | Value of the pair |

## `feed`

Describes changes to most sections of the user's profile, such as About, Photos, Posts, Friends, and Likes.

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |

## `first_name`

Field 'first\_name' of Topic 'user'

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |
| `value`  string | Value |

## `friends`

Describes changes to the Friends section of the user's profile.

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |
| `value`  object | Contents of the update |
| `uid`  numeric string | ID of friend |
| `verb`  enum {add, block, edit, edited, delete, follow, hide, mute, remove, unblock, unhide, update} | Type of operation |

## `gender`

Field 'gender' of Topic 'user'

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |
| `value`  string | Value |

## `hometown`

Describes changes to the Hometown section of the user's profile.

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |
| `value`  object | Contents of the update |
| `page`  numeric string | Page that corresponds with the update |
| `verb`  enum {add, block, edit, edited, delete, follow, hide, mute, remove, unblock, unhide, update} | Type of operation |

## `last_name`

Field 'last\_name' of Topic 'user'

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |
| `value`  string | Value |

## `likes`

Describes changes to the Music section of the user's profile.

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |
| `value`  object | Contents of the update |
| `page`  numeric string | Page that corresponds with the update |
| `verb`  enum {add, block, edit, edited, delete, follow, hide, mute, remove, unblock, unhide, update} | Type of operation |

## `live_videos`

Describes changes to the Live Video section of the user's profile.

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |
| `value`  object | Contents of the update |
| `id`  id | The ID of the live video |
| `status`  enum | The status of the live video |

## `location`

Describes changes to the Current City & Hometown section of the user's profile.

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |
| `value`  object | Contents of the update |
| `page`  numeric string | Page that corresponds with the update |
| `verb`  enum {add, block, edit, edited, delete, follow, hide, mute, remove, unblock, unhide, update} | Type of operation |

## `music`

Describes changes to the Music section of the user's profile.

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |
| `value`  object | Contents of the update |
| `page`  numeric string | Page that corresponds with the update |
| `verb`  enum {add, block, edit, edited, delete, follow, hide, mute, remove, unblock, unhide, update} | Type of operation |

## `name`

Describes changes to the Name section of the user's profile.

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |
| `first_name`  string | The new first name |
| `last_name`  string | The new last name |
| `localized_names`  object | The new localized names of the user |
| `middle_name`  string | The new middle name |
| `value`  string | The new name |

## `photos`

Describes changes to the Photos, Profile Photo, and Cover Photos sections of the user's profile.

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |
| `value`  object | Contents of the update |
| `verb`  enum {add, block, edit, edited, delete, follow, hide, mute, remove, unblock, unhide, update} | The type of action that triggered the update |
| `object_id`  numeric string | The ID of the photo |

## `pic_big_https`

Describes changes to the Profile Picture section of the user's profile.

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |
| `value`  string | The picture's URL |

## `pic_https`

Describes changes to the Profile Picture section of the user's profile.

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |
| `value`  string | The picture's URL |

## `pic_small_https`

Describes changes to the Profile Picture section of the user's profile.

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |
| `value`  string | The picture's URL |

## `pic_square_https`

Describes changes to the Profile Picture section of the user's profile.

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |
| `value`  string | The picture's URL |

## `platform`

Indicates that the user has enabled or disabled the Platform setting.

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |
| `verb`  enum | Type of operation |

## `quotes`

Describes changes to the Favorite Quotes section of the user's profile.

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |
| `value`  string | The new favorite quote |

## `status`

Describes changes to the Status section of the user's profile.

| Field | Description |
| --- | --- |
| `id`  token with structure: Post ID | ID of the status update |
| `field`  string | Name of the updated field |
| `value`  string | The new status |

## `television`

Describes changes to the TV Shows section of the user's profile.

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |
| `value`  object | Contents of the update |
| `page`  numeric string | Page that corresponds with the update |
| `verb`  enum {add, block, edit, edited, delete, follow, hide, mute, remove, unblock, unhide, update} | Type of operation |

## `videos`

Describes changes to the encoding status of the user's Uploaded Video.

| Field | Description |
| --- | --- |
| `field`  string | Name of the updated field |
| `value`  object | Contents of the update |
| `id`  id | ID of the video |
| `status`  object | Status of the video |
| `video_status`  enum | Status of the video |
