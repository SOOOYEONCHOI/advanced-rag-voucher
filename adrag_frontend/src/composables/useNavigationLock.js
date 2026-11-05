import { onBeforeUnmount, onMounted, unref } from 'vue';
import { onBeforeRouteLeave } from 'vue-router';

export const useNavigationLock = (locked, message) => {
  const isLocked = () => Boolean(unref(locked));

  const handleBeforeUnload = (event) => {
    if (!isLocked()) return;

    event.preventDefault();
    event.returnValue = '';
  };

  onBeforeRouteLeave(() => {
    if (!isLocked()) return true;

    window.alert(unref(message));
    return false;
  });

  onMounted(() => window.addEventListener('beforeunload', handleBeforeUnload));
  onBeforeUnmount(() => window.removeEventListener('beforeunload', handleBeforeUnload));
};
