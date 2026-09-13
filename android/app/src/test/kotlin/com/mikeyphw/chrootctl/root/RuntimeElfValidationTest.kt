package com.mikeyphw.chrootctl.root

import java.io.File
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class RuntimeElfValidationTest {
    @Test
    fun `arm64 little endian elf64 header is accepted`() {
        assertTrue(isAndroidArm64ElfHeader(elfHeader(machine = 183)))
    }

    @Test
    fun `wrong architecture is rejected`() {
        assertFalse(isAndroidArm64ElfHeader(elfHeader(machine = 62))) // x86_64
    }

    @Test
    fun `android linker64 interpreter is accepted`() {
        val file = elfFile("/system/bin/linker64")
        try {
            assertTrue(validateAndroidArm64Elf(file))
        } finally {
            file.delete()
        }
    }

    @Test
    fun `non android dynamic interpreter is rejected`() {
        val file = elfFile("/lib64/ld-linux-x86-64.so.2")
        try {
            assertFalse(validateAndroidArm64Elf(file))
        } finally {
            file.delete()
        }
    }

    private fun elfFile(interpreter: String): File {
        val header = elfHeader(machine = 183)
        putLong(header, 32, 64L) // e_phoff
        putShort(header, 54, 56) // e_phentsize
        putShort(header, 56, 1) // e_phnum
        val interp = (interpreter + "\u0000").toByteArray(Charsets.UTF_8)
        val program = ByteArray(56)
        putInt(program, 0, 3) // PT_INTERP
        putLong(program, 8, 120L) // p_offset
        putLong(program, 32, interp.size.toLong()) // p_filesz
        return File.createTempFile("chrootctl-elf-", ".bin").apply {
            writeBytes(header + program + interp)
        }
    }

    private fun elfHeader(machine: Int): ByteArray = ByteArray(64).also { header ->
        header[0] = 0x7f
        header[1] = 'E'.code.toByte()
        header[2] = 'L'.code.toByte()
        header[3] = 'F'.code.toByte()
        header[4] = 2 // ELFCLASS64
        header[5] = 1 // little endian
        putShort(header, 18, machine)
    }

    private fun putShort(bytes: ByteArray, offset: Int, value: Int) {
        bytes[offset] = (value and 0xff).toByte()
        bytes[offset + 1] = ((value ushr 8) and 0xff).toByte()
    }

    private fun putInt(bytes: ByteArray, offset: Int, value: Int) {
        repeat(4) { index -> bytes[offset + index] = ((value ushr (8 * index)) and 0xff).toByte() }
    }

    private fun putLong(bytes: ByteArray, offset: Int, value: Long) {
        repeat(8) { index -> bytes[offset + index] = ((value ushr (8 * index)) and 0xff).toByte() }
    }
}
