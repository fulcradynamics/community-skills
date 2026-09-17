<script lang="ts">
  import { user } from '$lib/user';
  import { onMount } from 'svelte';
  import { env } from '$env/dynamic/public';

  const OWNER_USER_ID = env.PUBLIC_OWNER_USER_ID;

  $: userId = $user.auth0UserInfo?.['fulcradynamics.com/userid'];
  $: isOwner = userId === OWNER_USER_ID;

  onMount(async () => {
    await user.init();
  });
</script>

{#if $user.authenticated && isOwner}
  <nav class="bg-fulcra-black/50 border-b border-fulcra-gray/20">
    <div class="max-w-7xl mx-auto px-4 py-3">
      <div class="flex items-center justify-between">
        <div class="flex items-center gap-4">
          <a
            href="/"
            class="text-fulcra-teal hover:text-fulcra-teal/80 font-medium"
          >
            Home
          </a>
          <a
            href="/harness"
            class="text-fulcra-teal hover:text-fulcra-teal/80 font-medium"
          >
            Harness Dashboard
          </a>
        </div>
        <div class="text-fulcra-gray text-sm">
          Owner
        </div>
      </div>
    </div>
  </nav>
{/if}

<style>
  nav {
    position: sticky;
    top: 0;
    z-index: 50;
  }
</style>
