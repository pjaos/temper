
import uos


class VFS():

    @staticmethod
    def GetFSInfo():
        """@brief Get the used and available disk space.
           @return A tuple containing
                   0 = The total disk space in bytes.
                   1 = The used disk space in bytes.
                   2 = The % used disk space."""
        stats = uos.statvfs("/")
        if stats and len(stats) == 10:
            f_bsize = stats[0]  # The file system block size in bytes
            f_blocks = stats[2]  # The size of fs in f_frsize units
            f_bfree = stats[3]  # The number of free blocks

            total_bytes = f_bsize * f_blocks
            free_space = f_bsize * f_bfree
            used_space = total_bytes - free_space

            if used_space > 0:
                percentage_used = (used_space / total_bytes) * 100.0
            else:
                percentage_used = 0.0

            return (total_bytes, used_space, percentage_used)

        raise Exception("GetFSInfo(): {} is invalid.".format(stats))

    @staticmethod
    def ShowFSInfo(uo):
        """@brief Show the file system info.
           @param A UO instance or None"""
        if uo:
            total_bytes, used_space, percentage_used = VFS.GetFSInfo()
            uo.info("File system information.")
            uo.info("Total Space (MB): {:.2f}".format(total_bytes / 1E6))
            uo.info("Used Space (MB):  {:.2f}".format(used_space / 1E6))
            uo.info("Used Space (%):   {:.1f}".format(percentage_used))
