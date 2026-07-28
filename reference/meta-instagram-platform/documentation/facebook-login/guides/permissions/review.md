# Permissions / Login Review



If your app asks for more than than `public_profile` and `email`, it will require review by Facebook before your app can be used by people other than the app&#039;s developers.

**Warning:** Due to changes to the review process and the high volume of submissions expected, it may take several weeks for submitted apps to complete review.

[Login Review Guide](https://developers.facebook.com/docs/facebook-login/review)

## Categories &#123;#categories&#125;

Permissions are placed into categories that reflect how they are presented to people and the review process.

Some sets of permissions are more sensitive than others and people can opt-out of providing access to them, even if you ask.  Optional permissions show up on a separate dialog during the login process, and the person can press the &#039;Skip&#039; button to not grant your app permission to access that set of data.

### Permissions That Do Not Require Review &#123;#noreview&#125;

* [Public profile (default) permissions](https://developers.facebook.com/docs/permissions/reference/public_profile).  The default includes some basic attributes about the person, which are part of a person&#039;s public profile on Facebook.  The default permissions are included as part of every permissions request, but require slightly different handling on the web and native mobile platforms.
* [Email permissions](https://developers.facebook.com/docs/permissions/reference/email).  This gives you access to the person&#039;s primary email address.

### Permissions That Require Review &#123;#requirereview&#125;

Permissions that require review are generally reviewed within 3 business days.  Some permissions may take up to 7 days to review, and are marked as such in the reference.

* [App friends](https://developers.facebook.com/docs/permissions/reference/user_friends).  This optional permission grants your app the ability to read a list of friends who also use your app.
* [Extended profile properties](https://developers.facebook.com/docs/facebook-login/permissions).  These permissions are all sensitive properties that may or may not be part of a person&#039;s public profile.
* [Extended permissions](https://developers.facebook.com/docs/facebook-login/permissions).  These include the most sensitive pieces of profile information.  One of the these permissions is publishing stories to a person&#039;s Facebook profile.  All extended permissions appear on a separate screen during the login flow so a person can decide if they want to grant them.
* [Page permissions](https://developers.facebook.com/docs/permissions/reference/manage_pages).  This permission allows you to administer any Facebook Pages that the person manages.
