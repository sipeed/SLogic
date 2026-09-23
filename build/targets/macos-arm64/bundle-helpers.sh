# Reusable macOS bundling/signing helpers, shared by the legacy sigrok products
# and the ngscope products (sourced by build-native). These reference the
# caller's globals at call time: BUILD_ROOT, OUTPUT, MACOS_DEPLOYMENT_TARGET,
# SIGN_IDENTITY, BUILD_PREFIX, MACOS_NOTARY_PROFILE.

# Complete the dependency closure for every Mach-O in the bundle, including
# Python extension modules. macdeployqt only handles Qt's direct dependency
# graph and otherwise leaves Homebrew paths in Python and image plugins.
close_bundle_dependencies() {
    local CONTENTS=$1
for pass in 1 2 3 4 5 6 7 8; do
    copied=0
    while IFS= read -r -d '' binary; do
        file "$binary" | grep -q Mach-O || continue
        while IFS= read -r dependency; do
            case "$dependency" in
                /System/*|/usr/lib/*|@executable_path/*|@loader_path/*|@rpath/*) continue ;;
                /opt/homebrew/*|/Users/*|/usr/local/*) ;;
                *) continue ;;
            esac

            if [[ "$dependency" == *'.framework/'* ]]; then
                framework_tail=${dependency#*.framework/}
                framework_name=$(basename "${dependency%%.framework/*}").framework
                bundled="$CONTENTS/Frameworks/$framework_name/$framework_tail"
                replacement="@executable_path/../Frameworks/$framework_name/$framework_tail"
                # Frameworks are copied by macdeployqt/Python deployment. An
                # external path here can also be the framework's own install ID.
                [ -e "$bundled" ] || { echo "Missing bundled framework dependency: $dependency" >&2; exit 1; }
            else
                name=$(basename "$dependency")
                bundled="$CONTENTS/Frameworks/$name"
                replacement="@executable_path/../Frameworks/$name"
                if [ ! -e "$bundled" ]; then
                    [ -e "$dependency" ] || { echo "Missing dependency: $dependency" >&2; exit 1; }
                    cp -L "$dependency" "$bundled"
                    chmod u+w "$bundled"
                    copied=1
                fi
            fi
            install_name_tool -change "$dependency" "$replacement" "$binary"
        done < <(otool -L "$binary" | tail -n +2 | awk '{print $1}')
    done < <(find "$CONTENTS" -type f -print0)
    [ "$copied" -eq 1 ] || break
done

# Normalize bundled library IDs as well, so an audit contains no build-host
# paths even when an LC_ID_DYLIB is not used for loading dependencies.
while IFS= read -r -d '' binary; do
    file "$binary" | grep -q Mach-O || continue
    id=$(otool -D "$binary" 2>/dev/null | tail -n +2 | head -n 1)
    case "$id" in
        /opt/homebrew/*|/Users/*|/usr/local/*)
            if [[ "$binary" == "$CONTENTS/Frameworks/"*.framework/* ]]; then
                relative=${binary#"$CONTENTS/Frameworks/"}
                install_name_tool -id "@executable_path/../Frameworks/$relative" "$binary"
            else
                install_name_tool -id "@executable_path/../Frameworks/$(basename "$binary")" "$binary"
            fi
            ;;
    esac
done < <(find "$CONTENTS/Frameworks" -type f -print0)

# Some non-framework Qt packages expose versioned dylib files through
# compatibility symlinks (for example libQt6Gui.6.dylib points at
# libQt6Gui.6.10.1.dylib). Copying with -L keeps the file but loses those
# aliases, leaving plugins with apparently valid yet unresolvable @rpath
# dependencies. Plugins can also introduce libraries outside macdeployqt's
# direct graph. Resolve both cases recursively and fail on an incomplete
# closure.
for pass in 1 2 3 4 5 6 7 8; do
    added=0
    while IFS= read -r -d '' binary; do
        file "$binary" | grep -q Mach-O || continue
        while IFS= read -r dependency; do
            case "$dependency" in
                @rpath/*.dylib)
                    name=${dependency#@rpath/}
                    [ -e "$CONTENTS/Frameworks/$name" ] && continue
                    stem=${name%.dylib}
                    candidate=
                    for possible in "$CONTENTS/Frameworks/$stem."*.dylib; do
                        [ -e "$possible" ] || continue
                        candidate=$possible
                        break
                    done
                    if [ -n "$candidate" ]; then
                        ln -s "$(basename "$candidate")" "$CONTENTS/Frameworks/$name"
                        added=1
                        continue
                    fi
                    source=
                    for possible in \
                        "$BUILD_ROOT/sr-darwin/lib/$name" \
                        "${BUILD_PREFIX:-/opt/homebrew}/lib/$name"; do
                        [ -e "$possible" ] || continue
                        source=$possible
                        break
                    done
                    if [ -z "$source" ]; then
                        echo "Unresolved bundled rpath dependency: $binary -> $dependency" >&2
                        exit 1
                    fi
                    cp -L "$source" "$CONTENTS/Frameworks/$name"
                    chmod u+w "$CONTENTS/Frameworks/$name"
                    install_name_tool -id \
                        "@executable_path/../Frameworks/$name" \
                        "$CONTENTS/Frameworks/$name"
                    added=1
                    ;;
            esac
        done < <(otool -L "$binary" | tail -n +2 | awk '{print $1}')
    done < <(find "$CONTENTS" -type f -print0)
    [ "$added" -eq 1 ] || break
done

# Python extension modules and some Qt plugins can retain @rpath references
# even after the matching libraries have been copied.  They may be loaded
# dynamically, so they cannot rely on an LC_RPATH inherited from the main
# executable.  Resolve these references explicitly against the Frameworks
# directory; the same layout is preserved in the portable CLI archive.
while IFS= read -r -d '' binary; do
    file "$binary" | grep -q Mach-O || continue
    while IFS= read -r dependency; do
        case "$dependency" in
            @rpath/*.dylib)
                name=${dependency#@rpath/}
                [ -e "$CONTENTS/Frameworks/$name" ] || {
                    echo "Unresolved bundled rpath dependency: $binary -> $dependency" >&2
                    exit 1
                }
                install_name_tool -change "$dependency" \
                    "@executable_path/../Frameworks/$name" "$binary"
                ;;
        esac
    done < <(otool -L "$binary" | tail -n +2 | awk '{print $1}')
done < <(find "$CONTENTS" -type f -print0)

# Libraries introduced while closing @rpath dependencies may themselves
# contain absolute references to the build prefix. Close and rewrite that
# graph once more before signing or creating the CLI archive.
for pass in 1 2 3 4 5 6 7 8; do
    copied=0
    while IFS= read -r -d '' binary; do
        file "$binary" | grep -q Mach-O || continue
        while IFS= read -r dependency; do
            case "$dependency" in
                /opt/homebrew/*|/Users/*|/usr/local/*) ;;
                *) continue ;;
            esac
            name=$(basename "$dependency")
            bundled="$CONTENTS/Frameworks/$name"
            if [ ! -e "$bundled" ]; then
                [ -e "$dependency" ] || {
                    echo "Missing transitive dependency: $binary -> $dependency" >&2
                    exit 1
                }
                cp -L "$dependency" "$bundled"
                chmod u+w "$bundled"
                install_name_tool -id \
                    "@executable_path/../Frameworks/$name" "$bundled"
                copied=1
            fi
            install_name_tool -change "$dependency" \
                "@executable_path/../Frameworks/$name" "$binary"
        done < <(otool -L "$binary" | tail -n +2 | awk '{print $1}')
    done < <(find "$CONTENTS" -type f -print0)
    [ "$copied" -eq 1 ] || break
done

# dylibbundler can map multiple original rpaths to the same bundle rpath.
# Current dyld rejects Mach-O images containing duplicate LC_RPATH commands.
while IFS= read -r -d '' binary; do
    file "$binary" | grep -q Mach-O || continue
    count=$(otool -l "$binary" | awk \
        '$1=="cmd"&&$2=="LC_RPATH"{seen=1;next} seen&&$1=="path"{if ($2=="@executable_path/../Frameworks/") n++; seen=0} END{print n+0}')
    while [ "$count" -gt 1 ]; do
        install_name_tool -delete_rpath @executable_path/../Frameworks/ "$binary"
        count=$((count - 1))
    done
done < <(find "$CONTENTS" -type f -print0)
}

# Info.plist does not control binary compatibility. Refuse to publish a bundle
# containing a Mach-O built for a newer macOS than the advertised minimum.
verify_deployment_target() {
    local CONTENTS=$1
deployment_mismatch=0
while IFS= read -r -d '' binary; do
    file "$binary" | grep -q Mach-O || continue
    while IFS= read -r minos; do
        [ -n "$minos" ] || continue
        if [ "$(printf '%s\n%s\n' "$MACOS_DEPLOYMENT_TARGET" "$minos" | sort -V | tail -n 1)" != "$MACOS_DEPLOYMENT_TARGET" ]; then
            echo "Deployment target mismatch: $binary requires macOS $minos (bundle advertises $MACOS_DEPLOYMENT_TARGET)" >&2
            deployment_mismatch=1
        fi
    done < <(otool -l "$binary" | awk \
        '$1=="cmd" && ($2=="LC_BUILD_VERSION" || $2=="LC_VERSION_MIN_MACOSX") { found=1; next }
         found && ($1=="minos" || $1=="version") { print $2; found=0 }')
done < <(find "$CONTENTS" -type f -print0)
[ "$deployment_mismatch" -eq 0 ] || exit 1
}

sign_bundle() {
    local app=$1
    while IFS= read -r -d '' binary; do
        file "$binary" | grep -q Mach-O || continue
        if [ "$SIGN_IDENTITY" = - ]; then
            codesign --force --sign - "$binary"
        else
            codesign --force --timestamp --options runtime --sign "$SIGN_IDENTITY" "$binary"
        fi
    done < <(find "$app/Contents" -type f -print0)
    if [ "$SIGN_IDENTITY" = - ]; then
        codesign --force --sign - "$app"
    else
        codesign --force --timestamp --options runtime --sign "$SIGN_IDENTITY" "$app"
    fi
    codesign --verify --deep --strict --verbose=2 "$app"
}

package_gui_dmg() {
    local app=$1 display_name=$2 executable=$3 volume_name=$4 output_name=$5
    local stage="$BUILD_ROOT/dmg-stage-$executable"
    local staged_app="$stage/$display_name.app"
    local dmg="$OUTPUT/$output_name"

    sign_bundle "$app"
    "$app/Contents/MacOS/$executable" --version \
        >"$BUILD_ROOT/$executable-bundle-check.txt" 2>&1

    rm -rf "$stage"
    mkdir -p "$stage"
    ditto "$app" "$staged_app"
    # Sign the exact copied tree that hdiutil will seal into the image.
    sign_bundle "$staged_app"
    ln -s /Applications "$stage/Applications"
    rm -f "$dmg"
    hdiutil create -fs HFS+ -format UDZO -volname "$volume_name" \
        -srcfolder "$stage" "$dmg"
    if [ "$SIGN_IDENTITY" = - ]; then
        codesign --force --sign - "$dmg"
    else
        codesign --force --timestamp --sign "$SIGN_IDENTITY" "$dmg"
    fi
    if [ -n "${MACOS_NOTARY_PROFILE:-}" ] && [ "$SIGN_IDENTITY" != - ]; then
        xcrun notarytool submit "$dmg" \
            --keychain-profile "$MACOS_NOTARY_PROFILE" --wait
        xcrun stapler staple "$dmg"
        xcrun stapler validate "$dmg"
        spctl --assess --type open --context context:primary-signature --verbose=2 "$dmg"
    fi
}
